"""
Webhook handler — receives events from Messenger and processes them.

Supports: new_message, message_edited, message_deleted.
Features: streaming responses, reply threading, file/image handling,
          session lifecycle, structured logging with timing.
"""
import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request

import config
from core import messenger
from core.context import build_llm_context
from core.llm_api import get_client

logger = logging.getLogger(__name__)
router = APIRouter()

# Per-room debounce state
_room_debounce: dict = {}

# Per-room active processing task (set while process_message is running)
_room_active_task: dict[int, asyncio.Task] = {}

# Per-room message counter (resets on new session)
_room_msg_count: dict[int, int] = {}

# Per-room persistent session data: {room_id: {"session_id": str, "created_at": str}}
_SESSIONS_FILE = os.path.join(config.DATA_DIR, "room_sessions.json")
_room_sessions: dict = {}


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------

def _load_room_sessions() -> None:
    global _room_sessions
    try:
        with open(_SESSIONS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            _room_sessions = {}
            for k, v in raw.items():
                if isinstance(v, str):
                    # Migrate old format: {room_id: session_id_string}
                    _room_sessions[int(k)] = {"session_id": v, "created_at": datetime.now(timezone.utc).isoformat()}
                else:
                    _room_sessions[int(k)] = v
        logger.info(f"[Sessions] Loaded {len(_room_sessions)} room session(s) from disk")
    except FileNotFoundError:
        _room_sessions = {}
    except Exception as e:
        logger.warning(f"[Sessions] Could not load room sessions: {e}")
        _room_sessions = {}


def _save_room_sessions() -> None:
    try:
        os.makedirs(os.path.dirname(_SESSIONS_FILE), exist_ok=True)
        with open(_SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in _room_sessions.items()}, f)
    except Exception as e:
        logger.warning(f"[Sessions] Could not save room sessions: {e}")


def _get_session_id(room_id: int) -> str | None:
    """Get session_id for a room, respecting max age."""
    entry = _room_sessions.get(room_id)
    if not entry:
        return None

    session_id = entry.get("session_id")
    if not session_id:
        return None

    # Check session age
    if config.SESSION_MAX_AGE_DAYS > 0:
        try:
            created = datetime.fromisoformat(entry["created_at"])
            age_days = (datetime.now(timezone.utc) - created).days
            if age_days >= config.SESSION_MAX_AGE_DAYS:
                logger.info(f"[Sessions] Room {room_id} session expired ({age_days}d old), starting fresh")
                del _room_sessions[room_id]
                _save_room_sessions()
                return None
        except (KeyError, ValueError):
            pass

    return session_id


def _set_session_id(room_id: int, session_id: str) -> None:
    _room_sessions[room_id] = {
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_room_sessions()


# Load on module import
_load_room_sessions()


# ---------------------------------------------------------------------------
# Webhook entry point
# ---------------------------------------------------------------------------

@router.post("/webhook")
async def handle_webhook(request: Request):
    payload = await request.json()
    event = payload.get("event")
    data = payload.get("data", {})
    room_id = payload.get("roomId")

    # --- Handle message edits ---
    if event == "message_edited":
        logger.info(f"[Webhook] Message edited in room {room_id}: id={data.get('messageId')}")
        return {"ok": True}

    # --- Handle message deletes ---
    if event == "message_deleted":
        logger.info(f"[Webhook] Message deleted in room {room_id}: id={data.get('messageId')}")
        return {"ok": True}

    if event != "new_message":
        return {"ok": True}

    content = data.get("content", "").strip()
    msg_type = data.get("type", "text")
    sender_name = data.get("senderName") or data.get("sender_name", "")
    is_bot = data.get("isBot") or data.get("is_bot", False)
    msg_id = data.get("id")

    # Ignore bot messages
    if sender_name == config.MESSENGER_BOT_NAME or is_bot:
        return {"ok": True}

    # Handle file/image messages — download and forward to LLM API
    file_info = None
    if msg_type == "image":
        file_name = data.get("fileName", "image")
        file_url = data.get("fileUrl", "")
        if not file_url:
            logger.warning(f"[Webhook] Image message {msg_id} has no fileUrl; refusing to process as an image")
            is_home = room_id == config.MESSENGER_HOME_ROOM_ID
            mention_tag = f"@{config.MESSENGER_BOT_NAME}"
            if room_id is not None and (is_home or mention_tag.lower() in content.lower()):
                asyncio.create_task(
                    messenger.send_message(
                        room_id,
                        "이미지 파일을 찾을 수 없어 처리할 수 없어요. 다시 업로드해주세요.",
                        reply_to_id=msg_id,
                    )
                )
            return {"ok": False, "error": "Image message missing fileUrl"}
        file_info = {"url": file_url, "name": file_name}
        if not content:
            content = f"[Image: {file_name}]"
    elif msg_type == "file":
        file_name = data.get("fileName", "file")
        file_url = data.get("fileUrl", "")
        if not file_url:
            logger.warning(f"[Webhook] File message {msg_id} has no fileUrl; refusing to process as a file")
            is_home = room_id == config.MESSENGER_HOME_ROOM_ID
            mention_tag = f"@{config.MESSENGER_BOT_NAME}"
            if room_id is not None and (is_home or mention_tag.lower() in content.lower()):
                asyncio.create_task(
                    messenger.send_message(
                        room_id,
                        "파일을 찾을 수 없어 처리할 수 없어요. 다시 업로드해주세요.",
                        reply_to_id=msg_id,
                    )
                )
            return {"ok": False, "error": "File message missing fileUrl"}
        file_info = {"url": file_url, "name": file_name}
        if not content:
            content = f"[File: {file_name}]"
    elif msg_type != "text":
        return {"ok": True}

    if not content:
        return {"ok": True}

    # In non-home rooms, only respond when @mentioned
    is_home = room_id == config.MESSENGER_HOME_ROOM_ID
    mention_tag = f"@{config.MESSENGER_BOT_NAME}"
    if not is_home and mention_tag.lower() not in content.lower():
        return {"ok": True}

    # Strip @mention
    clean_content = content
    if not is_home:
        clean_content = re.sub(
            rf"@{re.escape(config.MESSENGER_BOT_NAME)}", "", content, flags=re.IGNORECASE
        ).strip()
        if not clean_content:
            return {"ok": True}

    # Mark as read (best-effort)
    if msg_id:
        asyncio.create_task(messenger.mark_read(room_id, [msg_id]))

    reply_to_data = data.get("replyTo")
    _schedule_debounced(room_id, clean_content, sender_name, msg_id, file_info, reply_to_data)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Debounce — combines rapid-fire messages into one
# ---------------------------------------------------------------------------

def _schedule_debounced(room_id: int, content: str, sender_name: str, msg_id: int | None = None, file_info: dict | None = None, reply_to_data: dict | None = None) -> None:
    entry = _room_debounce.get(room_id)
    if entry and entry["task"] and not entry["task"].done():
        entry["task"].cancel()
        combined = entry["content"] + "\n" + content
        combined_files = list(entry.get("files") or [])
    else:
        combined = content
        combined_files = []

    # Cancel any in-flight process_message task for this room
    active = _room_active_task.pop(room_id, None)
    if active and not active.done():
        active.cancel()
    asyncio.create_task(messenger.stop_typing(room_id))

    if file_info:
        combined_files.append(file_info)

    async def _debounce():
        await asyncio.sleep(config.DEBOUNCE_SECONDS)
        final = _room_debounce.pop(room_id, None)
        if final:
            _room_active_task[room_id] = asyncio.current_task()
            try:
                await process_message(
                    room_id, final["content"], final["sender"], final.get("msg_id"),
                    file_infos=final.get("files"), reply_to_data=final.get("reply_to_data"),
                )
            finally:
                _room_active_task.pop(room_id, None)

    _room_debounce[room_id] = {
        "content": combined,
        "sender": sender_name,
        "msg_id": msg_id,
        "files": combined_files,
        "reply_to_data": reply_to_data,
        "task": asyncio.create_task(_debounce()),
    }


# ---------------------------------------------------------------------------
# Message processing — streaming or synchronous
# ---------------------------------------------------------------------------

def _build_message_header(room_name: str, room_id: int, is_group: bool, sender_name: str, reply_to_data: dict | None) -> str:
    """Build the bracketed context header prepended to every LLM message."""
    room_type = "group" if is_group else "DM"
    header = f"[Room: {room_name} (id:{room_id}, {room_type}) | From: {sender_name}]"
    if reply_to_data and not reply_to_data.get("isDeleted") and reply_to_data.get("content"):
        reply_sender = reply_to_data.get("senderName", "unknown")
        reply_content = reply_to_data["content"][:200]
        header += f"\n> {reply_sender}: \"{reply_content}\""
    return header


async def process_message(room_id: int, content: str, sender_name: str, reply_to_id: int | None = None, _is_retry: bool = False, file_infos: list | None = None, reply_to_data: dict | None = None) -> None:
    """Core message processing pipeline with structured logging and timing."""
    start = time.monotonic()
    log_prefix = f"[Room {room_id}] [{sender_name}]"
    logger.info(f"{log_prefix} Processing: {content[:80]!r}")

    # @clear: wipe session and return immediately
    if "@clear" in content.lower():
        _room_sessions.pop(room_id, None)
        _room_msg_count.pop(room_id, None)
        _save_room_sessions()
        await messenger.send_message(room_id, "컨텍스트가 초기화되었습니다. 새 대화를 시작하세요.")
        logger.info(f"{log_prefix} Session cleared by @clear command")
        return

    await messenger.send_typing(room_id, status_text=_STATUS_GENERATING)

    try:
        if not config.LLM_API_KEY:
            raise ValueError("LLM_API_KEY is not configured. Run: python setup.py")
        if not config.LLM_MODEL:
            raise ValueError("LLM_MODEL is not configured. Run: python setup.py")

        headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}
        existing_session_id = _get_session_id(room_id)

        # Download attached files from Messenger
        downloaded_files: list[tuple[str, bytes]] = []
        if file_infos:
            for fi in file_infos:
                result = await messenger.download_file(fi["url"])
                if result:
                    file_bytes, filename = result
                    downloaded_files.append((fi["name"], file_bytes))
                    logger.info(f"{log_prefix} Downloaded file: {fi['name']} ({len(file_bytes)} bytes)")
                else:
                    logger.warning(f"{log_prefix} Failed to download: {fi['name']}")

        room_info = await messenger.get_room_info(room_id)
        msg_header = _build_message_header(
            room_info["name"], room_id, room_info["isGroup"], sender_name, reply_to_data
        )

        # Always inject the full context (PROMPT.md + session vars + memory) so it
        # survives LLM history compaction and is present in every LLM call —
        # matching heartbeat behaviour where context is fresh on every tick.
        context = build_llm_context()
        user_content = f"{context}\n\n---\n\n{msg_header}\n{content}"

        if existing_session_id:
            # Track message count and nudge memory flush when session is getting long
            count = _room_msg_count.get(room_id, 0) + 1
            _room_msg_count[room_id] = count

            if count == config.MEMORY_FLUSH_THRESHOLD:
                user_content += (
                    "\n\n[System: This session is getting long. "
                    "Please save any important unsaved information from this conversation "
                    "to your memory file now, before context compaction loses it.]"
                )
                logger.info(f"{log_prefix} Memory flush hint injected at message #{count}")

            messages = [{"role": "user", "content": user_content}]
            llm_data = {
                "model": config.LLM_MODEL,
                "messages": json.dumps(messages),
                "session_id": existing_session_id,
            }
            logger.info(f"{log_prefix} Continuing session {existing_session_id} (msg #{count})")
        else:
            _room_msg_count[room_id] = 0  # Reset counter for new session
            messages = [{"role": "user", "content": user_content}]
            llm_data = {
                "model": config.LLM_MODEL,
                "messages": json.dumps(messages),
            }
            logger.info(f"{log_prefix} Starting new session")

        if config.STREAMING_ENABLED:
            reply = await _process_streaming(room_id, llm_data, headers, existing_session_id, log_prefix, reply_to_id, downloaded_files)
        else:
            reply = await _process_sync(room_id, llm_data, headers, existing_session_id, log_prefix, reply_to_id, downloaded_files)

        if reply is None:
            # Session was deleted (404) — retry once with a fresh session
            if not _is_retry:
                logger.info(f"{log_prefix} Retrying with fresh session after 404")
                await messenger.stop_typing(room_id)
                return await process_message(room_id, content, sender_name, reply_to_id, _is_retry=True, file_infos=file_infos)
            logger.warning(f"{log_prefix} Session 404 on retry — giving up")
            return

        elapsed = time.monotonic() - start
        logger.info(f"{log_prefix} Completed in {elapsed:.1f}s, reply={len(reply)} chars")

    except Exception as exc:
        elapsed = time.monotonic() - start
        logger.error(f"{log_prefix} Failed after {elapsed:.1f}s: {exc}", exc_info=True)
        try:
            if "Connect" in type(exc).__name__ or "Timeout" in type(exc).__name__:
                user_msg = "LLM 서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요."
            else:
                user_msg = f"오류: {str(exc)[:100]}"
            await messenger.send_message(room_id, user_msg)
        except Exception:
            pass
    finally:
        await messenger.stop_typing(room_id)


async def _save_session_from_response(room_id: int, result: dict, existing_session_id: str | None, log_prefix: str) -> None:
    """Save session_id returned by LLM API."""
    returned_session_id = result.get("x_session_id")
    if returned_session_id and returned_session_id != (existing_session_id or ""):
        _set_session_id(room_id, returned_session_id)
        logger.info(f"{log_prefix} Session saved as {returned_session_id}")


# ---------------------------------------------------------------------------
# Synchronous (non-streaming) processing
# ---------------------------------------------------------------------------

async def _process_sync(room_id: int, llm_data: dict, headers: dict, existing_session_id: str | None, log_prefix: str, reply_to_id: int | None, downloaded_files: list[tuple[str, bytes]] | None = None) -> str | None:
    """Send request, wait for full response, send to Messenger."""
    files_payload = [("files", (name, data, "application/octet-stream")) for name, data in (downloaded_files or [])]
    client = get_client()
    response = await client.post(
        f"{config.LLM_API_URL}/v1/chat/completions",
        data=llm_data,
        files=files_payload or None,
        headers=headers,
    )

    if response.status_code in (404, 500) and existing_session_id:
        logger.warning(f"{log_prefix} Session {existing_session_id} got {response.status_code}, starting fresh")
        _room_sessions.pop(room_id, None)
        _room_msg_count.pop(room_id, None)
        _save_room_sessions()
        return None

    response.raise_for_status()
    result = response.json()

    await _save_session_from_response(room_id, result, existing_session_id, log_prefix)
    reply = result["choices"][0]["message"]["content"]
    if reply.strip():
        await messenger.send_message(room_id, reply, reply_to_id=reply_to_id)
    else:
        fallback = "완료."
        await messenger.send_message(room_id, fallback, reply_to_id=reply_to_id)
        logger.warning(f"{log_prefix} LLM produced no text output — sent fallback acknowledgment")
        reply = fallback
    return reply


# ---------------------------------------------------------------------------
# Streaming processing — accumulates text silently, surfaces tool activity
# only through the ephemeral typing indicator at the bottom of the chat.
# ---------------------------------------------------------------------------

# Status shown in the typing indicator when the LLM is thinking/generating
# (i.e. no tool is currently running). Rendered as "{bot}님이 응답 생성 중...".
_STATUS_GENERATING = "응답 생성 중"

# How often to re-fire the typing event so the indicator stays visible during
# long tool calls. Must stay below the Messenger server-side auto-clear (15s)
# and the client-side safety timeout (20s).
_TYPING_REFRESH_INTERVAL_SECONDS = 10


def _format_tool_status(running_tools: dict[str, str]) -> str:
    """Return the typing-indicator text for the current set of running tools.

    Preserves insertion order so the indicator reads `websearch + python_coder
    사용 중` in the order the tools started. Falls back to the generating
    status when no tool is active.
    """
    if not running_tools:
        return _STATUS_GENERATING
    return " + ".join(running_tools.values()) + " 사용 중"


async def _process_streaming(room_id: int, llm_data: dict, headers: dict, existing_session_id: str | None, log_prefix: str, reply_to_id: int | None, downloaded_files: list[tuple[str, bytes]] | None = None) -> str | None:
    """Stream SSE from LLM API, accumulating text silently.

    UX model:
      - The final LLM reply is sent as a single Messenger message at the end
        of the turn — no progressive editing, no intermediate bubbles.
      - Tool activity is surfaced only through the typing indicator at the
        bottom of the chat: "{bot}님이 websearch 사용 중..." etc. Multiple
        parallel tools are joined with " + ".
      - While no tool is running, the indicator shows "{bot}님이 응답 생성 중...".
      - A background task re-fires the typing event every
        `_TYPING_REFRESH_INTERVAL_SECONDS` so the indicator survives long
        tool calls (Messenger auto-clears at 15s / client at 20s).
    """
    llm_data["stream"] = "true"
    files_payload = [("files", (name, data, "application/octet-stream")) for name, data in (downloaded_files or [])]

    full_text = ""
    running_tools: dict[str, str] = {}  # tool_call_id -> tool_name, insertion-ordered
    session_id_from_header: str | None = None
    status_msg_id: int | None = None  # ID of the live tool-status message in chat

    async def _refresh_typing() -> None:
        """Periodically re-fire the typing event so the indicator stays visible."""
        while True:
            await asyncio.sleep(_TYPING_REFRESH_INTERVAL_SECONDS)
            await messenger.send_typing(room_id, status_text=_format_tool_status(running_tools))

    refresh_task = asyncio.create_task(_refresh_typing())

    try:
        client = get_client()
        async with client.stream(
            "POST",
            f"{config.LLM_API_URL}/v1/chat/completions",
            data=llm_data,
            files=files_payload or None,
            headers=headers,
        ) as response:
            if response.status_code in (404, 500) and existing_session_id:
                logger.warning(f"{log_prefix} Session {existing_session_id} got {response.status_code}, starting fresh")
                _room_sessions.pop(room_id, None)
                _room_msg_count.pop(room_id, None)
                _save_room_sessions()
                return None

            response.raise_for_status()
            session_id_from_header = response.headers.get("x-session-id")

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break

                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                if "error" in event:
                    err = event.get("error") or {}
                    err_type = err.get("type", "stream_error")
                    err_message = str(err.get("message") or "").strip()
                    if not err_message:
                        err_message = json.dumps(err, ensure_ascii=False)
                    raise RuntimeError(f"LLM API stream error ({err_type}): {err_message}")

                if "tool_status" in event:
                    ts = event["tool_status"]
                    tool_name = ts.get("tool_name", "")
                    tool_key = ts.get("tool_call_id") or tool_name
                    status = ts.get("status", "")
                    if status == "started":
                        running_tools[tool_key] = tool_name
                        # Discard any pre-tool reasoning text
                        full_text = ""
                        status_text = _format_tool_status(running_tools)
                        if status_msg_id is None:
                            status_msg_id = await messenger.send_message_returning_id(
                                room_id, f"🔧 {status_text}..."
                            )
                        else:
                            await messenger.edit_message(status_msg_id, f"🔧 {status_text}...")
                    elif status in {"completed", "failed"}:
                        running_tools.pop(tool_key, None)
                        if running_tools and status_msg_id is not None:
                            status_text = _format_tool_status(running_tools)
                            await messenger.edit_message(status_msg_id, f"🔧 {status_text}...")
                    await messenger.send_typing(room_id, status_text=_format_tool_status(running_tools))
                    continue

                if "x_session_id" in event:
                    session_id_from_header = event["x_session_id"]

                choices = event.get("choices", [])
                if not choices:
                    continue
                text = choices[0].get("delta", {}).get("content", "")
                if text:
                    full_text += text

    except httpx.ReadTimeout:
        logger.warning(f"{log_prefix} Stream read timeout after collecting {len(full_text)} chars")
        if status_msg_id is not None:
            await messenger.delete_message(status_msg_id)
        if full_text.strip():
            await messenger.send_message(
                room_id,
                full_text.strip() + "\n\n⚠️ (응답이 시간 초과로 잘렸어요)",
                reply_to_id=reply_to_id,
            )
            return full_text
        raise
    except Exception:
        if status_msg_id is not None:
            try:
                await messenger.delete_message(status_msg_id)
            except Exception:
                pass
        raise
    finally:
        refresh_task.cancel()
        try:
            await refresh_task
        except asyncio.CancelledError:
            pass

    if session_id_from_header:
        result_like = {"x_session_id": session_id_from_header}
        await _save_session_from_response(room_id, result_like, existing_session_id, log_prefix)

    # Delete tool status message before sending the final reply
    if status_msg_id is not None:
        await messenger.delete_message(status_msg_id)

    final_text = full_text.strip()
    if final_text:
        await messenger.send_message(room_id, final_text, reply_to_id=reply_to_id)
        return final_text

    fallback = "완료."
    await messenger.send_message(room_id, fallback, reply_to_id=reply_to_id)
    logger.warning(f"{log_prefix} LLM produced no text output — sent fallback acknowledgment")
    return fallback


# ---------------------------------------------------------------------------
# External / incoming webhooks
# ---------------------------------------------------------------------------

@router.post("/webhook/incoming/{path:path}")
async def handle_incoming_webhook(path: str, request: Request):
    """Accept POST triggers from external services."""
    if config.WEBHOOK_INCOMING_SECRET:
        secret = request.headers.get("x-webhook-secret", "")
        if secret != config.WEBHOOK_INCOMING_SECRET:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    source = path.strip("/") or "external"
    if "message" in payload:
        content = f"[Webhook from {source}] {payload['message']}"
    else:
        content = f"[Webhook from {source}] {json.dumps(payload, ensure_ascii=False, indent=2)}"

    room_id = config.MESSENGER_HOME_ROOM_ID
    logger.info(f"[Webhook] Incoming from '{source}' → room {room_id}")
    _schedule_debounced(room_id, content, f"webhook:{source}")
    return {"ok": True}
