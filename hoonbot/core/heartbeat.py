"""
Heartbeat — proactive background loop with orchestrator pattern.

Each tick runs three phases:
  1. Planner  — LLM decomposes HEARTBEAT.md into discrete tasks with done_criteria
  2. Executor — each task runs through the full agent loop (with tools), one by one
  3. Validator — LLM checks which tasks didn't meet their done_criteria; retries once

Active hours and LLM cooldown (on connection failure) are enforced.
"""
import asyncio
import json
import logging
import os
import re
from datetime import datetime, time
from typing import Any, Callable, Awaitable

import httpx

import config
from core.context import build_llm_context
from core.llm_api import get_client

logger = logging.getLogger(__name__)

_HEARTBEAT_FILE = os.path.join(os.path.dirname(__file__), "..", "HEARTBEAT.md")

_llm_cooldown_until: float = 0.0

_PLANNER_SYSTEM = (
    "You are a task planner. Decompose the given checklist into discrete, executable tasks.\n"
    "Respond ONLY with a valid JSON array — no markdown fences, no explanation.\n"
    'Each item must have: {"id": <int>, "task": "<one-sentence action>", "done_criteria": "<measurable result>"}'
)

_VALIDATOR_SYSTEM = (
    "You are a task validator. Review the task results below and identify which tasks did NOT meet their done_criteria.\n"
    "Respond ONLY with a JSON array of integer IDs for incomplete tasks.\n"
    "If all tasks are complete, respond with: []"
)

_STALE_ERRORS = (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    return now >= start or now <= end


def _read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _extract_json(text: str, expected_type: type) -> Any:
    """Extract JSON from LLM text, handling optional ```json``` fences."""
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1)
    try:
        result = json.loads(text.strip())
        if isinstance(result, expected_type):
            return result
    except (json.JSONDecodeError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# LLM call primitives
# ---------------------------------------------------------------------------

async def _llm_stream(payload: dict, headers: dict) -> str:
    """Stream an LLM call; return accumulated text. Retries once on stale connection."""

    async def _once() -> str:
        buf = ""
        client = get_client()
        async with client.stream(
            "POST",
            f"{config.LLM_API_URL}/v1/chat/completions",
            data=payload,
            headers=headers,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:]
                if raw.strip() == "[DONE]":
                    break
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if "tool_status" in event:
                    ts = event["tool_status"]
                    logger.debug(f"[Heartbeat] Tool {ts.get('tool_name')}: {ts.get('status')}")
                    continue
                choices = event.get("choices", [])
                if choices:
                    chunk = choices[0].get("delta", {}).get("content", "")
                    if chunk:
                        buf += chunk
        return buf

    try:
        return await _once()
    except _STALE_ERRORS as exc:
        logger.warning(f"[Heartbeat] Stale connection ({type(exc).__name__}) — retrying once")
        return await _once()


async def _llm_sync(payload: dict, headers: dict) -> str:
    """Non-streaming LLM call (planner/validator — no tools); return response text."""
    client = get_client()
    resp = await client.post(
        f"{config.LLM_API_URL}/v1/chat/completions",
        data={**payload, "stream": "false"},
        headers=headers,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Orchestrator phases
# ---------------------------------------------------------------------------

async def _plan_tasks(checklist: str, context: str, headers: dict) -> list[dict]:
    """Phase 1: ask the LLM to decompose the checklist into tasks with done_criteria."""
    messages = [
        {"role": "system", "content": _PLANNER_SYSTEM},
        {"role": "user", "content": f"{context}\n\n## Checklist\n\n{checklist}"},
    ]
    payload = {"model": config.LLM_MODEL, "messages": json.dumps(messages)}
    try:
        text = await _llm_sync(payload, headers)
        tasks = _extract_json(text, list)
        if tasks and all(isinstance(t, dict) and "task" in t for t in tasks):
            # Ensure every task has a numeric id
            for i, t in enumerate(tasks, 1):
                t.setdefault("id", i)
            logger.info(f"[Heartbeat] Planner produced {len(tasks)} task(s)")
            return tasks
        logger.warning("[Heartbeat] Planner returned invalid structure — falling back to single task")
    except Exception as exc:
        logger.warning(f"[Heartbeat] Planner failed ({exc}) — falling back to single task")

    return [{"id": 1, "task": checklist.strip(), "done_criteria": "All checklist items addressed"}]


async def _execute_task(task: dict, context: str, tick_hour: str, headers: dict) -> str:
    """Phase 2: run one task through the full agent loop (with tools)."""
    task_id = task.get("id", 1)
    session_id = f"hb_{tick_hour}_t{task_id}"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    prompt = (
        f"[HEARTBEAT TASK {task_id} — {timestamp}]\n\n"
        "You are running a scheduled proactive task — no human is waiting. "
        "Complete the task below using your tools. "
        "Report exactly what you found or did.\n\n"
        f"**Task:** {task['task']}\n"
        f"**Done criteria:** {task.get('done_criteria', 'Task completed successfully')}"
    )
    messages = [{"role": "user", "content": f"{context}\n\n---\n\n{prompt}"}]
    payload = {
        "model": config.LLM_MODEL,
        "messages": json.dumps(messages),
        "stream": "true",
        "session_id": session_id,
    }
    try:
        result = await _llm_stream(payload, headers)
        logger.info(f"[Heartbeat] Task {task_id} finished ({len(result)} chars)")
        return result.strip() or "(no output)"
    except Exception as exc:
        logger.warning(f"[Heartbeat] Task {task_id} execution error: {exc}")
        return f"(error: {exc})"


async def _validate_tasks(tasks: list[dict], results: list[str], headers: dict) -> list[int]:
    """Phase 3: return IDs of tasks that did not meet their done_criteria."""
    items = []
    for task, result in zip(tasks, results):
        items.append(
            f"Task {task.get('id', '?')}: {task['task']}\n"
            f"Done criteria: {task.get('done_criteria', 'N/A')}\n"
            f"Result: {result[:600]}"
        )
    messages = [
        {"role": "system", "content": _VALIDATOR_SYSTEM},
        {"role": "user", "content": "\n\n---\n\n".join(items)},
    ]
    payload = {"model": config.LLM_MODEL, "messages": json.dumps(messages)}
    try:
        text = await _llm_sync(payload, headers)
        incomplete = _extract_json(text, list)
        if isinstance(incomplete, list):
            return [int(i) for i in incomplete if str(i).isdigit() or isinstance(i, int)]
    except Exception as exc:
        logger.warning(f"[Heartbeat] Validator failed ({exc}) — assuming all complete")
    return []


# ---------------------------------------------------------------------------
# Main tick
# ---------------------------------------------------------------------------

async def _run_once(send_fn: Callable[[int, str], Awaitable[None]]) -> None:
    """Execute one orchestrated heartbeat tick: plan → execute → validate → report."""
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
        logger.warning("[Heartbeat] LLM not configured — skipping tick")
        return

    context = build_llm_context()
    tick_hour = datetime.now().strftime("%Y%m%d%H")
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}

    logger.info(f"[Heartbeat] Starting orchestrated tick (model={config.LLM_MODEL})")

    full_text = ""
    try:
        # Phase 1 — Plan
        tasks = await _plan_tasks(checklist, context, headers)

        # Phase 2 — Execute each task
        results: list[str] = []
        for task in tasks:
            result = await _execute_task(task, context, tick_hour, headers)
            results.append(result)

        # Phase 3 — Validate; retry incomplete tasks once
        incomplete_ids = await _validate_tasks(tasks, results, headers)
        if incomplete_ids:
            logger.info(f"[Heartbeat] Retrying {len(incomplete_ids)} incomplete task(s): {incomplete_ids}")
            for i, task in enumerate(tasks):
                if task.get("id") in incomplete_ids:
                    results[i] = await _execute_task(task, context, tick_hour, headers)

        # Phase 4 — Compile report
        lines = []
        for task, result in zip(tasks, results):
            lines.append(f"**Task {task.get('id', '?')}: {task['task']}**\n{result}")
        full_text = "\n\n".join(lines)

    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        _llm_cooldown_until = asyncio.get_event_loop().time() + config.HEARTBEAT_LLM_COOLDOWN_SECONDS
        logger.warning(f"[Heartbeat] LLM unreachable ({type(exc).__name__}: {exc}). Cooling down.")
        return
    except httpx.TimeoutException as exc:
        if not full_text:
            _llm_cooldown_until = asyncio.get_event_loop().time() + config.HEARTBEAT_LLM_COOLDOWN_SECONDS
            logger.warning(f"[Heartbeat] LLM timeout with no response. Cooling down.")
            return
        logger.warning(f"[Heartbeat] Stream timeout after partial response — using what we have")
    except Exception as exc:
        logger.error(f"[Heartbeat] Unexpected error ({type(exc).__name__}): {exc}", exc_info=True)
        return

    reply = full_text.strip()
    if not reply:
        logger.info("[Heartbeat] No output — nothing to post")
    elif config.MESSENGER_HOME_ROOM_ID < 0:
        logger.warning("[Heartbeat] Home room not resolved — skipping post")
    else:
        logger.info(f"[Heartbeat] Posting report ({len(reply)} chars) to room {config.MESSENGER_HOME_ROOM_ID}")
        await send_fn(config.MESSENGER_HOME_ROOM_ID, f"**Autonomous agent**\n\n{reply}")


# ---------------------------------------------------------------------------
# Loop entry point
# ---------------------------------------------------------------------------

async def run_heartbeat_loop(send_fn: Callable[[int, str], Awaitable[None]]) -> None:
    """
    Heartbeat background loop.

    Sleeps HEARTBEAT_INTERVAL_SECONDS between ticks (first tick after one full
    interval so startup is never blocked). Active-hours and LLM-cooldown checks
    are applied on every tick.
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
            logger.error(f"[Heartbeat] Unhandled loop error: {exc}", exc_info=True)
