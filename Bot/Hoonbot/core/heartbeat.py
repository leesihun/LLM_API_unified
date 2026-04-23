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
from core.context import build_llm_context
from core.llm_api import get_client

logger = logging.getLogger(__name__)

_HEARTBEAT_FILE = os.path.join(os.path.dirname(__file__), "..", "HEARTBEAT.md")

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

    context = build_llm_context()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    heartbeat_prompt = (
        f"[HEARTBEAT {timestamp}]\n\n"
        "You are running a scheduled proactive check — there is no human waiting for a reply. "
        "Review the checklist below and complete any pending tasks using your tools. "
        "Load and execute any skills referenced in the checklist (read them from the skills directory first). "
        "Always reply with a summary of what you checked and found, even if everything is in order. "
        "Do not greet the user or explain that this is a scheduled check in your reply — "
        "just report what you did or found.\n\n"
        f"## Heartbeat Checklist\n\n{checklist}"
    )

    messages = [
        {"role": "user", "content": f"{context}\n\n---\n\n{heartbeat_prompt}"},
    ]

    logger.info(f"[Heartbeat] Calling LLM (model={config.LLM_MODEL}) at {config.LLM_API_URL}")

    payload = {
        "model": config.LLM_MODEL,
        "messages": json.dumps(messages),
        "stream": "true",
    }
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}

    async def _stream_once() -> str:
        """Open a fresh stream and accumulate text. Returns collected text."""
        text_buf = ""
        client = get_client()
        async with client.stream(
            "POST",
            f"{config.LLM_API_URL}/v1/chat/completions",
            data=payload,
            headers=headers,
        ) as response:
            response.raise_for_status()
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
                if "tool_status" in event:
                    ts = event["tool_status"]
                    logger.debug(
                        f"[Heartbeat] Tool {ts.get('tool_name')}: {ts.get('status')}"
                    )
                    continue
                choices = event.get("choices", [])
                if not choices:
                    continue
                chunk = choices[0].get("delta", {}).get("content", "")
                if chunk:
                    text_buf += chunk
        return text_buf

    # Stale-keepalive errors look like RemoteProtocolError / ReadError /
    # WriteError on the first byte. Retry once on a freshly-dialed socket
    # before giving up — the pool will have purged the dead connection.
    stale_errors = (
        httpx.RemoteProtocolError,
        httpx.ReadError,
        httpx.WriteError,
    )
    full_text = ""
    try:
        try:
            full_text = await _stream_once()
        except stale_errors as exc:
            logger.warning(
                f"[Heartbeat] Stale connection ({type(exc).__name__}: {exc}) — retrying once"
            )
            full_text = await _stream_once()

    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        # Real connect failure — server unreachable. Arm cooldown.
        _llm_cooldown_until = asyncio.get_event_loop().time() + config.HEARTBEAT_LLM_COOLDOWN_SECONDS
        logger.warning(
            f"[Heartbeat] LLM unreachable ({type(exc).__name__}: {exc}). "
            f"Cooling down for {config.HEARTBEAT_LLM_COOLDOWN_SECONDS}s"
        )
        return
    except httpx.TimeoutException as exc:
        # Timeout mid-request. Only cool down if we never received any bytes —
        # a late-stream hiccup shouldn't silence the next full interval.
        if not full_text:
            _llm_cooldown_until = asyncio.get_event_loop().time() + config.HEARTBEAT_LLM_COOLDOWN_SECONDS
            logger.warning(
                f"[Heartbeat] LLM timeout with no response ({type(exc).__name__}: {exc}). "
                f"Cooling down for {config.HEARTBEAT_LLM_COOLDOWN_SECONDS}s"
            )
            return
        logger.warning(
            f"[Heartbeat] Stream timeout after {len(full_text)} chars "
            f"({type(exc).__name__}) — using partial reply"
        )
    except Exception as exc:
        logger.error(
            f"[Heartbeat] Unexpected error during LLM call ({type(exc).__name__}): {exc}",
            exc_info=True,
        )
        return

    reply = full_text.strip()
    if not reply:
        logger.info("[Heartbeat] LLM returned empty reply — nothing to post")
    elif config.MESSENGER_HOME_ROOM_ID < 0:
        logger.warning("[Heartbeat] Home room not resolved — skipping post")
    else:
        logger.info(f"[Heartbeat] LLM replied ({len(reply)} chars) — posting to room {config.MESSENGER_HOME_ROOM_ID}")
        await send_fn(config.MESSENGER_HOME_ROOM_ID, f"**Autonomous agent**\n\n{reply}")


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
