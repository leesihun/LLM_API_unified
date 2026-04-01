"""
Hoonbot — entry point.

Startup sequence:
1. Health-check LLM API
2. Register bot with Messenger (get / restore API key)
3. Register webhook subscription (new_message, message_edited, message_deleted)
4. Resolve home room by name (if configured)
5. Catch up on missed messages
6. Start heartbeat loop
7. Serve FastAPI on HOONBOT_PORT
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI

import config
from core import messenger
from core.heartbeat import run_heartbeat_loop
from core.retry import with_retry
from handlers.health import router as health_router
from handlers.webhook import router as webhook_router, process_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hoonbot")

_KEY_FILE = os.path.join(os.path.dirname(__file__), "data", ".apikey")
_WEBHOOK_EVENTS = ["new_message", "message_edited", "message_deleted"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_saved_key() -> str:
    try:
        with open(_KEY_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def _save_key(key: str) -> None:
    os.makedirs(os.path.dirname(_KEY_FILE), exist_ok=True)
    with open(_KEY_FILE, "w") as f:
        f.write(key)


# ---------------------------------------------------------------------------
# Startup steps (each is a self-contained phase)
# ---------------------------------------------------------------------------

async def _probe_llm_url(client: httpx.AsyncClient, url: str) -> str | None:
    """Return url if its /health endpoint returns 200, else None."""
    try:
        resp = await client.get(f"{url}/health", timeout=5)
        return url if resp.status_code == 200 else None
    except Exception:
        return None


async def _autofind_llm_api() -> None:
    """Probe all candidate LLM API URLs concurrently; set config.LLM_API_URL to the first reachable one (in priority order)."""
    if not config.LLM_API_KEY:
        logger.warning("[Health] LLM API key not configured — run setup.py")
        return

    candidates = config.LLM_API_CANDIDATES
    logger.info(f"[Health] Probing LLM API candidates: {candidates}")

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*(_probe_llm_url(client, url) for url in candidates))

    reachable = {r for r in results if r}
    for url in candidates:  # honour priority order
        if url in reachable:
            if url != config.LLM_API_URL:
                logger.info(f"[Health] LLM API found at {url} (updating from {config.LLM_API_URL})")
                config.LLM_API_URL = url
            else:
                logger.info(f"[Health] LLM API reachable at {url}")
            return

    logger.warning(f"[Health] LLM API unreachable at all candidates: {candidates}")


async def _register_bot() -> None:
    """Restore saved API key or register a new bot with Messenger."""
    saved_key = _load_saved_key()
    if saved_key:
        messenger.set_api_key(saved_key)
        logger.info("[Messenger] Restored API key from disk")
    else:
        logger.info(f"[Messenger] Base URL: {config.MESSENGER_URL}")
        key = await with_retry(
            messenger.register_bot,
            config.MESSENGER_BOT_NAME,
            max_attempts=config.STARTUP_RETRY_ATTEMPTS,
            base_delay=config.STARTUP_RETRY_DELAY,
            label="Messenger bot registration",
        )
        messenger.set_api_key(key)
        _save_key(key)
        logger.info("[Messenger] Bot registered and key saved")


async def _fetch_bot_identity() -> None:
    """Fetch and cache the bot's user ID for session context injection."""
    bot_info = await messenger.get_bot_info()
    if bot_info:
        config.BOT_USER_ID = bot_info["id"]
        logger.info(f"[Hoonbot] Bot user ID: {config.BOT_USER_ID}")
    else:
        logger.warning("[Hoonbot] Could not fetch bot identity — bot_user_id will be 0 in context")


async def _subscribe_webhooks() -> None:
    """Register webhook subscriptions, re-registering the bot if the key is stale."""
    webhook_host = "aihoonbot.com" if config.USE_CLOUDFLARE else "localhost"
    webhook_scheme = "https" if config.USE_CLOUDFLARE else "http"
    webhook_url = f"{webhook_scheme}://{webhook_host}:{config.HOONBOT_PORT}/webhook"
    logger.info(f"[Messenger] Webhook target: {webhook_url}")

    retries = config.STARTUP_RETRY_ATTEMPTS
    delay = config.STARTUP_RETRY_DELAY

    try:
        await with_retry(
            messenger.register_webhook, webhook_url, _WEBHOOK_EVENTS,
            max_attempts=retries, base_delay=delay,
            label="Messenger webhook registration",
        )
        return
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 401:
            raise

    # API key rejected — re-register bot and retry
    logger.warning("[Messenger] API key unauthorized, re-registering bot")
    key = await with_retry(
        messenger.register_bot, config.MESSENGER_BOT_NAME,
        max_attempts=retries, base_delay=delay,
        label="Messenger bot registration",
    )
    messenger.set_api_key(key)
    _save_key(key)
    logger.info("[Messenger] Bot key refreshed and saved")

    await with_retry(
        messenger.register_webhook, webhook_url, _WEBHOOK_EVENTS,
        max_attempts=retries, base_delay=delay,
        label="Messenger webhook registration (after key refresh)",
    )


async def _resolve_home_room() -> None:
    """If MESSENGER_HOME_ROOM_NAME is set, look up the room ID by name."""
    if not config.MESSENGER_HOME_ROOM_NAME:
        return

    bot_info = await messenger.get_bot_info()
    if not bot_info:
        logger.warning("[Hoonbot] Could not fetch bot info for home room resolution")
        return

    resolved_id = await messenger.resolve_home_room_by_name(
        config.MESSENGER_HOME_ROOM_NAME, bot_info["id"],
    )
    if resolved_id is not None:
        config.MESSENGER_HOME_ROOM_ID = resolved_id
        logger.info(f"[Hoonbot] Home room resolved: '{config.MESSENGER_HOME_ROOM_NAME}' -> id={resolved_id}")
    else:
        config.MESSENGER_HOME_ROOM_ID = -1
        logger.warning(
            f"[Hoonbot] Home room '{config.MESSENGER_HOME_ROOM_NAME}' not found — "
            "heartbeat will not post until the room exists and Hoonbot is restarted"
        )


async def _catch_up() -> None:
    """Process the last unanswered human message in each room (handles offline period)."""
    bot_info = await messenger.get_bot_info()
    if not bot_info:
        logger.warning("[CatchUp] Could not get bot info, skipping")
        return

    rooms = await messenger.get_rooms(bot_info["id"])
    logger.info(f"[CatchUp] Scanning {len(rooms)} room(s) for missed messages")

    for room in rooms:
        room_id = room["id"]
        messages = await messenger.get_room_messages(room_id, limit=config.CATCHUP_MESSAGE_LIMIT)
        if not messages:
            continue

        # Find the last human text message
        last_human_idx = -1
        for i, msg in enumerate(messages):
            if (
                msg.get("senderName") != config.MESSENGER_BOT_NAME
                and not msg.get("isBot")
                and msg.get("type") == "text"
                and msg.get("content", "").strip()
            ):
                last_human_idx = i

        if last_human_idx == -1:
            continue

        # Skip if Hoonbot already replied after that message
        already_replied = any(
            msg.get("senderName") == config.MESSENGER_BOT_NAME
            for msg in messages[last_human_idx + 1:]
        )
        if already_replied:
            continue

        missed = messages[last_human_idx]
        content = missed.get("content", "").strip()
        sender = missed.get("senderName", "unknown")
        msg_id = missed.get("id")
        logger.info(f"[CatchUp] Room {room_id}: missed msg from {sender!r}: {content[:50]!r}")
        await process_message(room_id, content, sender, msg_id)


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(config.DATA_DIR, exist_ok=True)

    await _autofind_llm_api()
    await _register_bot()
    await _fetch_bot_identity()
    await _subscribe_webhooks()
    await _resolve_home_room()

    logger.info(f"[Hoonbot] Ready on port {config.HOONBOT_PORT}")
    logger.info(
        f"[Hoonbot] Streaming={'on' if config.STREAMING_ENABLED else 'off'}, "
        f"Session max age={config.SESSION_MAX_AGE_DAYS}d, "
        f"Debounce={config.DEBOUNCE_SECONDS}s"
    )

    asyncio.create_task(_catch_up())
    asyncio.create_task(run_heartbeat_loop(messenger.send_message))

    yield

    await messenger.close_client()
    logger.info("[Hoonbot] Shutdown complete")


app = FastAPI(title="Hoonbot", lifespan=lifespan)
app.include_router(health_router)
app.include_router(webhook_router)


if __name__ == "__main__":
    uvicorn.run(
        "hoonbot:app",
        host=config.HOONBOT_HOST,
        port=config.HOONBOT_PORT,
        reload=False,
    )
