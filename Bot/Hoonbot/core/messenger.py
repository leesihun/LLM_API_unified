"""Async client for the Huni Messenger bot API with persistent connection pool."""
import logging
import os
from typing import Optional

import httpx
import config
from core.retry import with_retry

logger = logging.getLogger(__name__)

# Runtime state — populated during startup
_api_key: str = ""

# Persistent HTTP client — shared across all requests
_client: Optional[httpx.AsyncClient] = None

# Room info cache: room_id -> {"name": str, "isGroup": bool}
_room_cache: dict[int, dict] = {}


def _get_client() -> httpx.AsyncClient:
    """Get or create the shared httpx client."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            trust_env=False,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _client


async def close_client() -> None:
    """Close the shared client. Call during application shutdown."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


def set_api_key(key: str) -> None:
    global _api_key
    _api_key = key
    config.MESSENGER_API_KEY = key


def _headers() -> dict:
    return {"x-api-key": _api_key, "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Bot registration & webhooks
# ---------------------------------------------------------------------------

async def register_bot(name: str) -> str:
    """Register bot with Messenger and return its API key."""
    client = _get_client()
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
    bot_id = data.get("bot", {}).get("id") or data.get("id")
    logger.info(f"[Messenger] Bot registered: {name} (id={bot_id})")
    return key


async def register_webhook(url: str, events: list) -> None:
    """Subscribe to Messenger events. Idempotent."""
    client = _get_client()
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

    resp = await client.post(
        f"{config.MESSENGER_URL}/api/webhooks",
        headers=_headers(),
        json={"url": url, "events": events},
    )
    resp.raise_for_status()
    logger.info(f"[Messenger] Webhook registered: {url} for events={events}")


# ---------------------------------------------------------------------------
# Messages — send, edit, delete
# ---------------------------------------------------------------------------

def _split_message(text: str, limit: int) -> list:
    """Split text into chunks that respect paragraph and line boundaries."""
    if len(text) <= limit:
        return [text]

    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        cut = text.rfind("\n\n", 0, limit)
        if cut == -1:
            cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = text.rfind(" ", 0, limit)
        if cut == -1:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return chunks


async def send_message(room_id: int, content: str, reply_to_id: int | None = None) -> None:
    """Send a message, automatically splitting if it exceeds the character limit."""
    chunks = _split_message(content, config.MAX_MESSAGE_LENGTH)
    for i, chunk in enumerate(chunks):
        async def _send(c=chunk, first=(i == 0)):
            client = _get_client()
            body = {"roomId": room_id, "content": c, "type": "text"}
            if reply_to_id and first:
                body["replyToId"] = reply_to_id
            resp = await client.post(
                f"{config.MESSENGER_URL}/api/send-message",
                headers=_headers(),
                json=body,
            )
            resp.raise_for_status()

        await with_retry(_send, label="Messenger send", max_attempts=3)


async def send_message_returning_id(room_id: int, content: str) -> int | None:
    """Send a message and return its ID (for later editing/deletion)."""
    try:
        client = _get_client()
        resp = await client.post(
            f"{config.MESSENGER_URL}/api/send-message",
            headers=_headers(),
            json={"roomId": room_id, "content": content, "type": "text"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("id") or data.get("id")
    except Exception:
        return None


async def edit_message(message_id: int, content: str) -> None:
    """Edit a previously sent message."""
    try:
        client = _get_client()
        resp = await client.post(
            f"{config.MESSENGER_URL}/api/edit-message",
            headers=_headers(),
            json={"messageId": message_id, "content": content},
        )
        resp.raise_for_status()
    except Exception:
        pass  # Best-effort


async def delete_message(message_id: int) -> None:
    """Soft-delete a previously sent message."""
    try:
        client = _get_client()
        resp = await client.post(
            f"{config.MESSENGER_URL}/api/delete-message",
            headers=_headers(),
            json={"messageId": message_id},
        )
        resp.raise_for_status()
    except Exception:
        pass  # Best-effort


async def mark_read(room_id: int, message_ids: list) -> None:
    """Mark messages as read (best-effort)."""
    if not message_ids:
        return
    try:
        client = _get_client()
        await client.post(
            f"{config.MESSENGER_URL}/api/mark-read",
            headers=_headers(),
            json={"roomId": room_id, "messageIds": message_ids},
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Typing indicators
# ---------------------------------------------------------------------------

async def send_typing(room_id: int) -> None:
    try:
        client = _get_client()
        await client.post(
            f"{config.MESSENGER_URL}/api/typing",
            headers=_headers(),
            json={"roomId": room_id},
        )
    except Exception:
        pass  # Best-effort


async def stop_typing(room_id: int) -> None:
    try:
        client = _get_client()
        await client.post(
            f"{config.MESSENGER_URL}/api/stop-typing",
            headers=_headers(),
            json={"roomId": room_id},
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Bot info & room queries
# ---------------------------------------------------------------------------

async def get_bot_info() -> Optional[dict]:
    try:
        client = _get_client()
        resp = await client.get(
            f"{config.MESSENGER_URL}/api/bots/me",
            headers=_headers(),
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


async def get_room_info(room_id: int) -> dict:
    """Return room metadata (name, isGroup) for a given room ID.

    Fetches all bot rooms on first cache miss and caches the results.
    Falls back to {"name": str(room_id), "isGroup": False} if the room
    cannot be resolved.
    """
    if room_id in _room_cache:
        return _room_cache[room_id]

    bot_info = await get_bot_info()
    if bot_info:
        rooms = await get_rooms(bot_info["id"])
        for room in rooms:
            _room_cache[room["id"]] = {
                "name": room.get("name") or str(room["id"]),
                "isGroup": bool(room.get("isGroup", False)),
            }

    return _room_cache.get(room_id, {"name": str(room_id), "isGroup": False})


async def get_rooms(bot_user_id: int) -> list:
    try:
        client = _get_client()
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


async def resolve_home_room_by_name(name: str, bot_user_id: int) -> Optional[int]:
    """
    Find the room whose name matches `name` (case-insensitive) among the bot's
    rooms and return its ID. Returns None if no match is found.
    """
    rooms = await get_rooms(bot_user_id)
    name_lower = name.strip().lower()
    for room in rooms:
        room_name = (room.get("name") or "").strip().lower()
        if room_name == name_lower:
            return room["id"]
    return None


async def download_file(file_url: str) -> tuple[bytes, str] | None:
    """Download a file from Messenger given a relative fileUrl path.

    Returns (file_bytes, filename) or None on failure.
    """
    try:
        client = _get_client()
        full_url = f"{config.MESSENGER_URL}{file_url}"
        resp = await client.get(full_url, headers={"x-api-key": _api_key})
        resp.raise_for_status()
        filename = file_url.rsplit("/", 1)[-1]
        return resp.content, filename
    except Exception as e:
        logger.warning(f"[Messenger] File download failed for {file_url}: {e}")
        return None


async def send_file(room_id: int, file_path: str, caption: str | None = None) -> int:
    """Upload a local file to a room. Returns message_id on success."""
    client = _get_client()
    with open(file_path, "rb") as f:
        data = {"roomId": str(room_id)}
        if caption:
            data["content"] = caption
        resp = await client.post(
            f"{config.MESSENGER_URL}/api/send-file",
            headers={"x-api-key": _api_key},  # no Content-Type — httpx sets multipart boundary
            data=data,
            files={"file": (os.path.basename(file_path), f)},
        )
    resp.raise_for_status()
    result = resp.json()
    msg_id = result.get("message", {}).get("id") or result.get("id")
    if not msg_id:
        raise ValueError("message_id missing in upload response")
    return msg_id


async def send_base64(room_id: int, data_url: str, file_name: str | None = None, caption: str | None = None) -> int:
    """Send a base64 image to a room. data_url must include the full data URL prefix
    (e.g. 'data:image/png;base64,...'). Returns message_id on success."""
    client = _get_client()
    body: dict = {"roomId": room_id, "data": data_url}
    if file_name:
        body["fileName"] = file_name
    if caption:
        body["content"] = caption
    resp = await client.post(
        f"{config.MESSENGER_URL}/api/send-base64",
        headers={"x-api-key": _api_key},
        json=body,  # httpx sets Content-Type: application/json automatically
    )
    resp.raise_for_status()
    result = resp.json()
    msg_id = result.get("message", {}).get("id") or result.get("id")
    if not msg_id:
        raise ValueError("message_id missing in upload response")
    return msg_id


async def get_room_messages(room_id: int, limit: int = 20) -> list:
    try:
        client = _get_client()
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
