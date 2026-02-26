"""Async client for the Huni Messenger bot API."""
import logging
from typing import List, Optional

import httpx
import config
from core.retry import with_retry

logger = logging.getLogger(__name__)

# Runtime state — populated during startup
_api_key: str = ""
_bot_id: Optional[int] = None


def set_api_key(key: str) -> None:
    global _api_key
    _api_key = key
    config.MESSENGER_API_KEY = key


def get_api_key() -> str:
    return _api_key


def _headers() -> dict:
    return {"x-api-key": _api_key, "Content-Type": "application/json"}


async def register_bot(name: str) -> str:
    """
    Register Hoonbot with Messenger and return its API key.
    If a bot with the same name already exists, Messenger returns a fresh key.
    If a non-bot user has the same name, Messenger returns 409.
    """
    global _bot_id
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        resp = await client.post(
            f"{config.MESSENGER_URL}/api/bots",
            json={"name": name},
        )
        if resp.status_code == 409:
            raise RuntimeError(
                f'Messenger bot name conflict for "{name}". '
                "A non-bot user already has this name. "
                "Set HOONBOT_BOT_NAME to a unique bot name."
            )
        resp.raise_for_status()
        data = resp.json()
        key = data.get("apiKey") or data.get("key") or data.get("api_key", "")
        _bot_id = data.get("bot", {}).get("id") or data.get("id")
        logger.info(f"[Messenger] Bot registered: {name} (id={_bot_id})")
        return key


async def register_webhook(url: str, events: List[str]) -> None:
    """Subscribe to Messenger events. Idempotent — existing webhooks with same URL are reused."""
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        # Check existing webhooks first
        resp = await client.get(
            f"{config.MESSENGER_URL}/api/webhooks",
            headers=_headers(),
        )
        if resp.status_code == 200:
            existing = resp.json()
            for wh in existing:
                if wh.get("url") == url:
                    logger.info(f"[Messenger] Webhook already registered: {url}")
                    return

        # Register new webhook (room_id omitted = all rooms)
        resp = await client.post(
            f"{config.MESSENGER_URL}/api/webhooks",
            headers=_headers(),
            json={"url": url, "events": events},
        )
        resp.raise_for_status()
        logger.info(f"[Messenger] Webhook registered: {url} for events={events}")


def _split_message(text: str, limit: int) -> list:
    """Split text into chunks that respect paragraph and line boundaries."""
    if len(text) <= limit:
        return [text]

    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        # Try to split at a double newline (paragraph break)
        cut = text.rfind("\n\n", 0, limit)
        if cut == -1:
            # Try single newline
            cut = text.rfind("\n", 0, limit)
        if cut == -1:
            # Try space
            cut = text.rfind(" ", 0, limit)
        if cut == -1:
            # Hard cut
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return chunks


async def send_message(room_id: int, content: str) -> None:
    """Send a message, automatically splitting if it exceeds the character limit."""
    chunks = _split_message(content, config.MAX_MESSAGE_LENGTH)
    for chunk in chunks:
        async def _send(c=chunk):
            async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
                resp = await client.post(
                    f"{config.MESSENGER_URL}/api/send-message",
                    headers=_headers(),
                    json={"roomId": room_id, "content": c, "type": "text"},
                )
                resp.raise_for_status()

        await with_retry(_send, label="Messenger send", max_attempts=3)


async def send_typing(room_id: int) -> None:
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            await client.post(
                f"{config.MESSENGER_URL}/api/typing",
                headers=_headers(),
                json={"roomId": room_id},
            )
    except Exception:
        pass  # Typing indicators are best-effort


async def stop_typing(room_id: int) -> None:
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            await client.post(
                f"{config.MESSENGER_URL}/api/stop-typing",
                headers=_headers(),
                json={"roomId": room_id},
            )
    except Exception:
        pass


async def get_bot_info() -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            resp = await client.get(
                f"{config.MESSENGER_URL}/api/bots/me",
                headers=_headers(),
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None


async def get_rooms(bot_user_id: int) -> list:
    """Fetch rooms the bot belongs to."""
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            resp = await client.get(
                f"{config.MESSENGER_URL}/api/rooms",
                headers=_headers(),
                params={"userId": bot_user_id},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        logger.warning(f"[Messenger] get_rooms failed: {exc}")
    return []


async def get_room_messages(room_id: int, limit: int = 20) -> list:
    """Fetch recent messages from a room (oldest-first order)."""
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            resp = await client.get(
                f"{config.MESSENGER_URL}/api/messages/{room_id}",
                headers=_headers(),
                params={"limit": limit},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        logger.warning(f"[Messenger] get_room_messages({room_id}) failed: {exc}")
    return []
