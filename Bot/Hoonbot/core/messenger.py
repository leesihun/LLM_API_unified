"""Async client for the Huni Messenger bot API with persistent connection pool."""
import logging
from typing import Optional

import httpx
import config
from core.retry import with_retry

logger = logging.getLogger(__name__)

# Runtime state — populated during startup
_api_key: str = ""
_bot_id: Optional[int] = None

# Persistent HTTP client — shared across all requests
_client: Optional[httpx.AsyncClient] = None


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


def get_api_key() -> str:
    return _api_key


def _headers() -> dict:
    return {"x-api-key": _api_key, "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Bot registration & webhooks
# ---------------------------------------------------------------------------

async def register_bot(name: str) -> str:
    """Register bot with Messenger and return its API key."""
    global _bot_id
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
    _bot_id = data.get("bot", {}).get("id") or data.get("id")
    logger.info(f"[Messenger] Bot registered: {name} (id={_bot_id})")
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
# Messages — send, edit, delete, search
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


def _insert_line_breaks(text: str, line_limit: int = 60) -> str:
    """Wrap overly long lines for better readability in chat bubbles."""
    if line_limit <= 0:
        raise ValueError("line_limit must be greater than 0")

    wrapped_lines: list[str] = []
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line
        if not line:
            wrapped_lines.append("")
            continue

        while len(line) > line_limit:
            cut = line.rfind(" ", 0, line_limit + 1)
            if cut <= 0:
                cut = line_limit
            wrapped_lines.append(line[:cut].rstrip())
            line = line[cut:].lstrip()

        wrapped_lines.append(line)

    return "\n".join(wrapped_lines)


async def send_message(room_id: int, content: str, reply_to_id: int | None = None) -> None:
    """Send a message, automatically splitting if it exceeds the character limit."""
    formatted = _insert_line_breaks(content)
    chunks = _split_message(formatted, config.MAX_MESSAGE_LENGTH)
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


async def search_messages(query: str, room_id: int | None = None, limit: int = 20) -> list:
    """Search messages across rooms or within a specific room."""
    try:
        client = _get_client()
        params = {"q": query, "limit": limit}
        if room_id:
            params["roomId"] = room_id
        resp = await client.get(
            f"{config.MESSENGER_URL}/api/search",
            headers=_headers(),
            params=params,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as exc:
        logger.warning(f"[Messenger] search_messages failed: {exc}")
    return []


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
# Files & images
# ---------------------------------------------------------------------------

async def send_file(room_id: int, file_path: str, caption: str = "") -> None:
    """Upload and send a file to a room."""
    try:
        client = _get_client()
        with open(file_path, "rb") as f:
            resp = await client.post(
                f"{config.MESSENGER_URL}/api/send-file",
                headers={"x-api-key": _api_key},
                data={"roomId": str(room_id), "content": caption},
                files={"file": f},
            )
            resp.raise_for_status()
    except Exception as exc:
        logger.warning(f"[Messenger] send_file failed: {exc}")


async def send_base64_image(room_id: int, base64_data: str, filename: str = "image.png", caption: str = "") -> None:
    """Send a base64-encoded image to a room."""
    try:
        client = _get_client()
        resp = await client.post(
            f"{config.MESSENGER_URL}/api/send-base64",
            headers=_headers(),
            json={
                "roomId": room_id,
                "data": base64_data,
                "fileName": filename,
                "content": caption,
            },
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning(f"[Messenger] send_base64_image failed: {exc}")


# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------

async def pin_message(message_id: int, room_id: int) -> None:
    try:
        client = _get_client()
        resp = await client.post(
            f"{config.MESSENGER_URL}/api/pins",
            headers=_headers(),
            json={"messageId": message_id, "roomId": room_id},
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning(f"[Messenger] pin_message failed: {exc}")


async def unpin_message(message_id: int) -> None:
    try:
        client = _get_client()
        resp = await client.delete(
            f"{config.MESSENGER_URL}/api/pins/{message_id}",
            headers=_headers(),
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning(f"[Messenger] unpin_message failed: {exc}")


async def get_pins(room_id: int) -> list:
    try:
        client = _get_client()
        resp = await client.get(
            f"{config.MESSENGER_URL}/api/pins/{room_id}",
            headers=_headers(),
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as exc:
        logger.warning(f"[Messenger] get_pins failed: {exc}")
    return []


# ---------------------------------------------------------------------------
# Web watchers
# ---------------------------------------------------------------------------

async def create_watcher(url: str, room_id: int, interval_seconds: int = 60) -> dict | None:
    """Create a URL change watcher that posts to a room when content changes."""
    try:
        client = _get_client()
        resp = await client.post(
            f"{config.MESSENGER_URL}/api/watchers",
            headers=_headers(),
            json={"url": url, "roomId": room_id, "intervalSeconds": interval_seconds},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning(f"[Messenger] create_watcher failed: {exc}")
        return None


async def list_watchers() -> list:
    try:
        client = _get_client()
        resp = await client.get(
            f"{config.MESSENGER_URL}/api/watchers",
            headers=_headers(),
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as exc:
        logger.warning(f"[Messenger] list_watchers failed: {exc}")
    return []


async def delete_watcher(watcher_id: int) -> None:
    try:
        client = _get_client()
        resp = await client.delete(
            f"{config.MESSENGER_URL}/api/watchers/{watcher_id}",
            headers=_headers(),
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning(f"[Messenger] delete_watcher failed: {exc}")


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------

async def create_room(name: str, member_names: list, is_group: bool = True) -> dict | None:
    try:
        client = _get_client()
        resp = await client.post(
            f"{config.MESSENGER_URL}/api/create-room",
            headers=_headers(),
            json={
                "name": name,
                "isGroup": is_group,
                "creatorName": config.MESSENGER_BOT_NAME,
                "memberNames": member_names,
            },
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning(f"[Messenger] create_room failed: {exc}")
        return None


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
