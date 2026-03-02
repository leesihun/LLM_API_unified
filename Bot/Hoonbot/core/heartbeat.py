"""
Heartbeat — proactive background loop.

Reads HEARTBEAT.md as a task checklist and runs the LLM agent against it
on a configurable interval (HEARTBEAT_INTERVAL_SECONDS, default 3600s).

The LLM receives the checklist + current memory and may use all tools
(websearch, file ops, python, shell, etc.) to complete tasks proactively.
Any non-empty reply is posted to the configured home Messenger room.

Active hours and LLM cooldown (on connection failure) are enforced.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, time
from typing import Callable, Awaitable

import httpx

import config

logger = logging.getLogger(__name__)

_HEARTBEAT_FILE = os.path.join(os.path.dirname(__file__), "..", "HEARTBEAT.md")
_MEMORY_FILE = os.path.join(config.DATA_DIR, "memory.md")
_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "..", "skills")

# Monotonic deadline before which LLM calls are suppressed after a connection failure
_llm_cooldown_until: float = 0.0


def _within_active_hours() -> bool:
    now = datetime.now().time()
    try:
        start = time.fromisoformat(config.HEARTBEAT_ACTIVE_START)
        end = time.fromisoformat(config.HEARTBEAT_ACTIVE_END)
    except ValueError:
        logger.warning("[Heartbeat] Invalid active-hours config — treating as always active")
        return True
    if start <= end:
        return start <= now <= end
    # Overnight window (e.g. 22:00–06:00)
    return now >= start or now <= end


def _read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


async def _run_once(send_fn: Callable[[int, str], Awaitable[None]]) -> None:
    """Execute one heartbeat tick: call the LLM with the checklist, post reply."""
    global _llm_cooldown_until

    loop_time = asyncio.get_event_loop().time()
    if loop_time < _llm_cooldown_until:
        remaining = int(_llm_cooldown_until - loop_time)
        logger.info(f"[Heartbeat] LLM cooldown active ({remaining}s remaining) — skipping tick")
        return

    checklist = _read_file(_HEARTBEAT_FILE)
    if not checklist.strip():
        logger.info("[Heartbeat] HEARTBEAT.md is empty or missing — skipping tick")
        return

    if not config.LLM_API_KEY or not config.LLM_MODEL:
        logger.warning("[Heartbeat] LLM not configured (no API key or model) — skipping tick")
        return

    memory = _read_file(_MEMORY_FILE)
    abs_memory_path = os.path.abspath(_MEMORY_FILE)

    # Reuse the same system-prompt loader as the webhook handler
    from handlers.webhook import _load_system_prompt
    system_prompt_base = _load_system_prompt()

    abs_skills_path = os.path.abspath(_SKILLS_DIR)

    context = system_prompt_base
    context += f"\n\n---\n\n## Memory File Location for This Session\n\nAbsolute path: `{abs_memory_path}`"
    context += f"\n\n## Skills Directory\n\nAbsolute path: `{abs_skills_path}`"
    if memory:
        context += f"\n\n## Current Memory Content\n\n{memory}"
    else:
        context += "\n\n## Current Memory\n\n(No memory saved yet)"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    heartbeat_prompt = (
        f"[HEARTBEAT {timestamp}]\n\n"
        "You are running a scheduled proactive check — there is no human waiting for a reply. "
        "Review the checklist below and complete any pending tasks using your tools. "
        "Load and execute any skills referenced in the checklist (read them from the skills directory first). "
        "If everything is in order and nothing needs attention, reply with exactly: HEARTBEAT_OK\n"
        "Do not greet the user or explain that this is a scheduled check in your reply — "
        "just report what you did or found.\n\n"
        f"## Heartbeat Checklist\n\n{checklist}"
    )

    messages = [
        {"role": "user", "content": f"{context}\n\n---\n\n{heartbeat_prompt}"},
    ]

    logger.info(f"[Heartbeat] Calling LLM (model={config.LLM_MODEL})")
    try:
        async with httpx.AsyncClient(timeout=float(config.LLM_TIMEOUT_SECONDS)) as client:
            response = await client.post(
                f"{config.LLM_API_URL}/v1/chat/completions",
                data={
                    "model": config.LLM_MODEL,
                    "messages": json.dumps(messages),
                },
                headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
            )
            response.raise_for_status()
            result = response.json()

        reply = (result["choices"][0]["message"]["content"] or "").strip()
        if not reply:
            logger.info("[Heartbeat] LLM returned empty reply — nothing to post")
        elif reply.startswith("HEARTBEAT_OK"):
            logger.info("[Heartbeat] Nothing needs attention — suppressing reply")
        else:
            logger.info(f"[Heartbeat] LLM replied ({len(reply)} chars) — posting to room {config.MESSENGER_HOME_ROOM_ID}")
            await send_fn(config.MESSENGER_HOME_ROOM_ID, f"**Autonomous agent**\n\n{reply}")

    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        _llm_cooldown_until = asyncio.get_event_loop().time() + config.HEARTBEAT_LLM_COOLDOWN_SECONDS
        logger.warning(
            f"[Heartbeat] LLM connection failed: {exc}. "
            f"Cooling down for {config.HEARTBEAT_LLM_COOLDOWN_SECONDS}s"
        )
    except Exception as exc:
        logger.error(f"[Heartbeat] Unexpected error during LLM call: {exc}", exc_info=True)


async def run_heartbeat_loop(send_fn: Callable[[int, str], Awaitable[None]]) -> None:
    """
    Heartbeat background loop.

    Sleeps HEARTBEAT_INTERVAL_SECONDS between ticks (first tick is after one
    full interval, so startup is never blocked).  Active-hours and LLM-cooldown
    checks are applied on every tick.

    send_fn — async callable (room_id, text) used to post results; pass
              core.messenger.send_message.
    """
    if not config.HEARTBEAT_ENABLED:
        logger.info("[Heartbeat] Disabled by config (HOONBOT_HEARTBEAT_ENABLED=false)")
        return

    logger.info(
        f"[Heartbeat] Loop started — interval={config.HEARTBEAT_INTERVAL_SECONDS}s, "
        f"active hours={config.HEARTBEAT_ACTIVE_START}–{config.HEARTBEAT_ACTIVE_END}"
    )

    while True:
        await asyncio.sleep(config.HEARTBEAT_INTERVAL_SECONDS)

        if not _within_active_hours():
            logger.debug("[Heartbeat] Outside active hours — skipping tick")
            continue

        try:
            await _run_once(send_fn)
        except Exception as exc:
            # Belt-and-suspenders: _run_once already catches most errors
            logger.error(f"[Heartbeat] Unhandled loop error: {exc}", exc_info=True)
