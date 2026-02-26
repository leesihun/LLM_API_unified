"""
Hoonbot — entry point.

Startup sequence:
1. Register bot with Messenger (get / restore API key)
2. Register webhook subscription
3. Serve FastAPI on HOONBOT_PORT

All state is stored in memory.md and managed via LLM_API_fast tools.
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

# Key storage file so we survive restarts without re-registering
_KEY_FILE = os.path.join(os.path.dirname(__file__), "data", ".apikey")


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


async def _catch_up() -> None:
    """
    On startup, find the last unanswered human message in each room Hoonbot
    belongs to and process it — handles messages sent while Hoonbot was offline.
    """
    bot_info = await messenger.get_bot_info()
    if not bot_info:
        logger.warning("[CatchUp] Could not get bot info, skipping")
        return

    bot_id = bot_info["id"]
    rooms = await messenger.get_rooms(bot_id)
    logger.info(f"[CatchUp] Scanning {len(rooms)} room(s) for missed messages")

    for room in rooms:
        room_id = room["id"]
        messages = await messenger.get_room_messages(room_id, limit=20)
        if not messages:
            continue

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

        hoonbot_replied = any(
            msg.get("senderName") == config.MESSENGER_BOT_NAME
            for msg in messages[last_human_idx + 1:]
        )
        if hoonbot_replied:
            continue

        missed = messages[last_human_idx]
        content = missed.get("content", "").strip()
        sender = missed.get("senderName", "unknown")
        logger.info(f"[CatchUp] Room {room_id}: missed msg from {sender!r}: {content[:50]!r}")
        await process_message(room_id, content, sender)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure data directory exists
    os.makedirs(config.DATA_DIR, exist_ok=True)

    # --- Bot registration ---
    saved_key = _load_saved_key()
    if saved_key:
        messenger.set_api_key(saved_key)
        logger.info("[Messenger] Restored API key from disk")
    else:
        logger.info(f"[Messenger] Base URL: {config.MESSENGER_URL}")
        key = await with_retry(
            messenger.register_bot,
            config.MESSENGER_BOT_NAME,
            max_attempts=6,
            base_delay=1.0,
            label="Messenger bot registration",
        )
        messenger.set_api_key(key)
        _save_key(key)
        logger.info("[Messenger] Bot registered and key saved")

    # --- Webhook subscription ---
    webhook_host = "aihoonbot.com" if config.USE_CLOUDFLARE else "localhost"
    webhook_scheme = "https" if config.USE_CLOUDFLARE else "http"
    webhook_url = f"{webhook_scheme}://{webhook_host}:{config.HOONBOT_PORT}/webhook"
    logger.info(f"[Messenger] Webhook target: {webhook_url}")
    try:
        await with_retry(
            messenger.register_webhook,
            webhook_url,
            ["new_message"],
            max_attempts=6,
            base_delay=1.0,
            label="Messenger webhook registration",
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 401:
            raise
        logger.warning("[Messenger] API key unauthorized, re-registering bot")
        key = await with_retry(
            messenger.register_bot,
            config.MESSENGER_BOT_NAME,
            max_attempts=6,
            base_delay=1.0,
            label="Messenger bot registration",
        )
        messenger.set_api_key(key)
        _save_key(key)
        logger.info("[Messenger] Bot key refreshed and saved")
        await with_retry(
            messenger.register_webhook,
            webhook_url,
            ["new_message"],
            max_attempts=6,
            base_delay=1.0,
            label="Messenger webhook registration (after key refresh)",
        )

    logger.info(f"[Hoonbot] Ready on port {config.HOONBOT_PORT}")

    # --- Catch up on missed messages ---
    asyncio.create_task(_catch_up())

    # --- Heartbeat loop ---
    asyncio.create_task(run_heartbeat_loop(messenger.send_message))

    yield

    # --- Shutdown ---
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
