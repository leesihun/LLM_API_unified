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

logger = logging.getLogger(__name__)
router = APIRouter()

# Per-room debounce state
_room_debounce: dict = {}

MEMORY_FILE = os.path.join(config.DATA_DIR, "memory.md")

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
# System prompt & memory
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_CACHE: str = ""


def _load_system_prompt() -> str:
    """Return cached system prompt (loaded from PROMPT.md on first call)."""
    global _SYSTEM_PROMPT_CACHE
    if _SYSTEM_PROMPT_CACHE:
        return _SYSTEM_PROMPT_CACHE
    prompt_file = os.path.join(os.path.dirname(__file__), "..", "PROMPT.md")
    try:
        with open(prompt_file, "r", encoding="utf-8") as f:
            _SYSTEM_PROMPT_CACHE = f.read()
    except FileNotFoundError:
        _SYSTEM_PROMPT_CACHE = "You are a helpful AI assistant."
    return _SYSTEM_PROMPT_CACHE


def _read_memory() -> str:
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


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
        logger.info(f"[Webhook] Message edited in room {room_id}: id={data.get('id')}")
        return {"ok": True}

    # --- Handle message deletes ---
    if event == "message_deleted":
        logger.info(f"[Webhook] Message deleted in room {room_id}: id={data.get('id')}")
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

    # Handle file/image messages — convert to text description
    if msg_type == "image":
        file_name = data.get("fileName", "image")
        file_url = data.get("fileUrl", "")
        content = f"[User sent an image: {file_name}] {content or ''}".strip()
        if file_url:
            content += f"\nFile URL: {file_url}"
    elif msg_type == "file":
        file_name = data.get("fileName", "file")
        file_url = data.get("fileUrl", "")
        content = f"[User sent a file: {file_name}] {content or ''}".strip()
        if file_url:
            content += f"\nFile URL: {file_url}"
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

    _schedule_debounced(room_id, clean_content, sender_name, msg_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Debounce — combines rapid-fire messages into one
# ---------------------------------------------------------------------------

def _schedule_debounced(room_id: int, content: str, sender_name: str, msg_id: int | None = None) -> None:
    entry = _room_debounce.get(room_id)
    if entry and entry["task"] and not entry["task"].done():
        entry["task"].cancel()
        combined = entry["content"] + "\n" + content
    else:
        combined = content

    async def _debounce():
        await asyncio.sleep(config.DEBOUNCE_SECONDS)
        final = _room_debounce.pop(room_id, None)
        if final:
            await process_message(room_id, final["content"], final["sender"], final.get("msg_id"))

    _room_debounce[room_id] = {
        "content": combined,
        "sender": sender_name,
        "msg_id": msg_id,
        "task": asyncio.create_task(_debounce()),
    }


# ---------------------------------------------------------------------------
# Message processing — streaming or synchronous
# ---------------------------------------------------------------------------

async def process_message(room_id: int, content: str, sender_name: str, reply_to_id: int | None = None) -> None:
    """Core message processing pipeline with structured logging and timing."""
    start = time.monotonic()
    log_prefix = f"[Room {room_id}] [{sender_name}]"
    logger.info(f"{log_prefix} Processing: {content[:80]!r}")

    await messenger.send_typing(room_id)

    try:
        if not config.LLM_API_KEY:
            raise ValueError("LLM_API_KEY is not configured. Run: python setup.py")
        if not config.LLM_MODEL:
            raise ValueError("LLM_MODEL is not configured. Run: python setup.py")

        headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}
        existing_session_id = _get_session_id(room_id)

        if existing_session_id:
            messages = [{"role": "user", "content": content}]
            llm_data = {
                "model": config.LLM_MODEL,
                "messages": json.dumps(messages),
                "session_id": existing_session_id,
            }
            logger.info(f"{log_prefix} Continuing session {existing_session_id}")
        else:
            system_prompt_base = _load_system_prompt()
            memory = _read_memory()
            abs_memory_path = os.path.abspath(MEMORY_FILE)

            context = system_prompt_base
            context += f"\n\n---\n\n## Memory File Location for This Session\n\nAbsolute path: `{abs_memory_path}`"
            if memory:
                context += f"\n\n## Current Memory Content\n\n{memory}"
            else:
                context += "\n\n## Current Memory\n\n(No memory saved yet)"

            messages = [
                {"role": "user", "content": f"{context}\n\n---\n\nUser: {content}"},
            ]
            llm_data = {
                "model": config.LLM_MODEL,
                "messages": json.dumps(messages),
            }
            logger.info(f"{log_prefix} Starting new session")

        if config.STREAMING_ENABLED:
            reply = await _process_streaming(room_id, llm_data, headers, existing_session_id, log_prefix, reply_to_id)
        else:
            reply = await _process_sync(room_id, llm_data, headers, existing_session_id, log_prefix, reply_to_id)

        if reply is None:
            # Session was deleted — retry handled inside, nothing more to do
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


async def _handle_session_404(room_id: int, content: str, sender_name: str, existing_session_id: str, log_prefix: str) -> None:
    """Handle 404 (deleted session) by clearing and retrying."""
    logger.warning(f"{log_prefix} Session {existing_session_id} not found, starting fresh")
    if room_id in _room_sessions:
        del _room_sessions[room_id]
        _save_room_sessions()
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

async def _process_sync(room_id: int, llm_data: dict, headers: dict, existing_session_id: str | None, log_prefix: str, reply_to_id: int | None) -> str | None:
    """Send request, wait for full response, send to Messenger."""
    async with httpx.AsyncClient(timeout=float(config.LLM_TIMEOUT_SECONDS)) as client:
        response = await client.post(
            f"{config.LLM_API_URL}/v1/chat/completions",
            data=llm_data,
            headers=headers,
        )

        if response.status_code == 404 and existing_session_id:
            await _handle_session_404(room_id, llm_data.get("content", ""), "", existing_session_id, log_prefix)
            return None

        response.raise_for_status()
        result = response.json()

    await _save_session_from_response(room_id, result, existing_session_id, log_prefix)
    reply = result["choices"][0]["message"]["content"]
    await messenger.send_message(room_id, reply, reply_to_id=reply_to_id)
    return reply


# ---------------------------------------------------------------------------
# Streaming processing — shows tool status in real time
# ---------------------------------------------------------------------------

async def _process_streaming(room_id: int, llm_data: dict, headers: dict, existing_session_id: str | None, log_prefix: str, reply_to_id: int | None) -> str | None:
    """Stream SSE from LLM API, send tool status updates, then final reply."""
    llm_data["stream"] = "true"

    full_text = ""
    tool_status_msgs: list[int] = []  # message IDs for tool status messages we sent
    session_id_from_header = None

    try:
        async with httpx.AsyncClient(timeout=float(config.LLM_TIMEOUT_SECONDS)) as client:
            async with client.stream(
                "POST",
                f"{config.LLM_API_URL}/v1/chat/completions",
                data=llm_data,
                headers=headers,
            ) as response:
                if response.status_code == 404 and existing_session_id:
                    await _handle_session_404(room_id, "", "", existing_session_id, log_prefix)
                    return None

                response.raise_for_status()

                # Check for session_id in response headers
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

                    # Handle tool status events
                    if "tool_status" in event:
                        ts = event["tool_status"]
                        tool_name = ts.get("tool_name", "")
                        status = ts.get("status", "")
                        if status == "started":
                            msg_id = await messenger.send_message_returning_id(
                                room_id, f"*{tool_name} ...*"
                            )
                            if msg_id:
                                tool_status_msgs.append(msg_id)
                        elif status == "completed" and tool_status_msgs:
                            duration = ts.get("duration", 0)
                            await messenger.edit_message(
                                tool_status_msgs[-1],
                                f"*{tool_name} completed ({duration:.1f}s)*"
                            )
                        continue

                    # Handle session_id in event payload
                    if "x_session_id" in event:
                        session_id_from_header = event["x_session_id"]

                    # Handle text content
                    choices = event.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        full_text += text

    except httpx.ReadTimeout:
        logger.warning(f"{log_prefix} Stream read timeout after collecting {len(full_text)} chars")
        if not full_text:
            raise

    # Save session
    if session_id_from_header:
        result_like = {"x_session_id": session_id_from_header}
        await _save_session_from_response(room_id, result_like, existing_session_id, log_prefix)

    # Clean up tool status messages
    for mid in tool_status_msgs:
        await messenger.delete_message(mid)

    # Send the final reply
    if full_text.strip():
        await messenger.send_message(room_id, full_text.strip(), reply_to_id=reply_to_id)

    return full_text


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
