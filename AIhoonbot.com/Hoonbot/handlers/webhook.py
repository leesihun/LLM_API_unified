"""
Webhook handler — receives new_message events from Messenger and processes them.

Uses LLM_API_fast agent system to handle all operations (tools, memory updates, etc).
"""
import asyncio
import json
import logging
import os
import re

import httpx
from fastapi import APIRouter, HTTPException, Request

import config
from core import messenger

logger = logging.getLogger(__name__)
router = APIRouter()

# Per-room debounce
_room_debounce: dict = {}
_DEBOUNCE_SECONDS = 1.5

MEMORY_FILE = os.path.join(config.DATA_DIR, "memory.md")


def _read_memory() -> str:
    """Read memory.md, return empty string if not exists."""
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _load_system_prompt() -> str:
    """Load PROMPT.md as system prompt (unified prompt file)."""
    prompt_file = os.path.join(os.path.dirname(__file__), "..", "PROMPT.md")
    try:
        with open(prompt_file, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "You are a helpful AI assistant."


@router.post("/webhook")
async def handle_webhook(request: Request):
    payload = await request.json()
    event = payload.get("event")

    if event != "new_message":
        return {"ok": True}

    data = payload.get("data", {})
    room_id = payload.get("roomId")
    content = data.get("content", "").strip()
    msg_type = data.get("type", "text")
    sender_name = data.get("senderName") or data.get("sender_name", "")
    is_bot = data.get("isBot") or data.get("is_bot", False)

    if msg_type != "text" or not content:
        return {"ok": True}

    if sender_name == config.MESSENGER_BOT_NAME or is_bot:
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

    _schedule_debounced(room_id, clean_content, sender_name)
    return {"ok": True}


def _schedule_debounced(room_id: int, content: str, sender_name: str) -> None:
    """Debounce message processing."""
    entry = _room_debounce.get(room_id)
    if entry and entry["task"] and not entry["task"].done():
        entry["task"].cancel()
        combined = entry["content"] + "\n" + content
    else:
        combined = content

    async def _debounce():
        await asyncio.sleep(_DEBOUNCE_SECONDS)
        final = _room_debounce.pop(room_id, None)
        if final:
            await process_message(room_id, final["content"], final["sender"])

    _room_debounce[room_id] = {
        "content": combined,
        "sender": sender_name,
        "task": asyncio.create_task(_debounce()),
    }


async def process_message(room_id: int, content: str, sender_name: str) -> None:
    """Core message processing pipeline."""
    await messenger.send_typing(room_id)

    try:
        # Validate configuration
        if not config.LLM_API_KEY:
            raise ValueError("LLM_API_KEY is not configured. Run: python setup.py")
        if not config.LLM_MODEL:
            raise ValueError("LLM_MODEL is not configured. Run: python setup.py")

        # Load context
        system_prompt_base = _load_system_prompt()
        memory = _read_memory()

        # Get absolute path to memory file
        abs_memory_path = os.path.abspath(MEMORY_FILE)

        # Build context: PROMPT.md + memory location + current memory
        # NOTE: LLM_API_fast agents inject their own system prompt, so we include
        # PROMPT.md as the FIRST user message instead to ensure it's read
        context = system_prompt_base
        context += f"\n\n---\n\n## Memory File Location for This Session\n\nAbsolute path: `{abs_memory_path}`"
        if memory:
            context += f"\n\n## Current Memory Content\n\n{memory}"
        else:
            context += f"\n\n## Current Memory\n\n(No memory saved yet)"

        # Build messages: PROMPT context first, then user message
        # This ensures PROMPT.md isn't overridden by agent's default system prompt
        messages = [
            {"role": "user", "content": f"{context}\n\n---\n\nUser: {content}"},
        ]

        # Call LLM_API_fast with auto agent (has access to all tools)
        headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}
        llm_data = {
            "model": config.LLM_MODEL,
            "messages": json.dumps(messages),
            "agent_type": "auto",  # Auto agent uses tools automatically
        }

        logger.info(f"[LLM] Calling {config.LLM_API_URL}/v1/chat/completions with model={config.LLM_MODEL}")
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{config.LLM_API_URL}/v1/chat/completions",
                data=llm_data,
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()

        reply = result["choices"][0]["message"]["content"]

        # Send reply back to Messenger
        await messenger.send_message(room_id, reply)

    except Exception as exc:
        logger.error(f"[Error] process_message failed: {exc}", exc_info=True)
        try:
            if "Connect" in type(exc).__name__ or "Timeout" in type(exc).__name__:
                user_msg = "⚠️ LLM 서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요."
            else:
                user_msg = f"⚠️ 오류: {str(exc)[:100]}"
            await messenger.send_message(room_id, user_msg)
        except Exception:
            pass
    finally:
        await messenger.stop_typing(room_id)


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
