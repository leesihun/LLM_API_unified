"""Master-side watcher that relays finished cluster task results to Messenger.

When a Messenger user issues an `@<node>` directive, `cluster_client` queues a
task on the master and posts "Queued cluster task X". The slave executes it and
writes the result back into the master's cluster store — but nothing delivered
that result to the user. This loop closes the gap: it watches for tasks that
reach a terminal state and posts their result (or error) back to the originating
room, keyed by `metadata.room_id` saved at submission time.

Master-only. No-op unless cluster + delegation are enabled.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx

import config

logger = logging.getLogger(__name__)

_TERMINAL = {"completed", "failed", "cancelled"}
_RELAYED_FILE = Path(config.DATA_DIR) / "relayed_tasks.json"


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if getattr(config, "CLUSTER_TOKEN", ""):
        headers["x-cluster-token"] = config.CLUSTER_TOKEN
    return headers


def _load_relayed() -> set[str]:
    try:
        data = json.loads(_RELAYED_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(str(x) for x in data)
    except FileNotFoundError:
        return set()
    except Exception as exc:  # corrupt file — start clean rather than crash
        logger.warning("[Relay] Could not read %s (%s); starting empty", _RELAYED_FILE, exc)
    return set()


def _save_relayed(relayed: set[str]) -> None:
    try:
        _RELAYED_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Cap the persisted set so it can't grow without bound.
        items = list(relayed)
        if len(items) > 2000:
            items = items[-2000:]
        _RELAYED_FILE.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.warning("[Relay] Could not persist relayed set: %s", exc)


async def _list_terminal_tasks(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    resp = await client.get(
        f"{config.CLUSTER_MASTER_API_URL}/api/cluster/tasks",
        params={"include_completed": "true"},
        headers=_headers(),
    )
    resp.raise_for_status()
    tasks = resp.json().get("tasks") or []
    return [t for t in tasks if t.get("status") in _TERMINAL]


async def _load_full_task(client: httpx.AsyncClient, task_id: str) -> dict[str, Any] | None:
    """Fetch the un-truncated task (the list endpoint strips result to 300 chars)."""
    resp = await client.get(
        f"{config.CLUSTER_MASTER_API_URL}/api/cluster/tasks/{task_id}",
        headers=_headers(),
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json().get("task")


def _format_message(task: dict[str, Any]) -> str | None:
    """Build the Messenger message for a finished task, or None to skip it."""
    meta = task.get("metadata") or {}
    directive = meta.get("directive") or task.get("target_node") or "cluster"
    node = task.get("leased_by") or task.get("target_node") or "?"
    status = task.get("status")
    if status == "completed":
        result = (task.get("result") or "").strip() or "(no output)"
        return f"**@{directive} → {node}**\n\n{result}"
    if status == "failed":
        err = (task.get("error") or "Task failed with no error detail").strip()
        return f"**@{directive} → {node} failed**\n\n{err}"
    if status == "cancelled":
        return f"**@{directive} → {node} cancelled**"
    return None


async def run_cluster_relay_loop(send_fn) -> None:
    """Poll for terminal Messenger-sourced tasks and relay their results.

    *send_fn* is an async ``(room_id: int, content: str) -> None`` — typically
    ``messenger.send_message``.
    """
    if not getattr(config, "CLUSTER_ENABLED", False):
        logger.info("[Relay] Cluster disabled — relay loop not started")
        return
    if getattr(config, "CLUSTER_ROLE", "master") != "master":
        return
    if not getattr(config, "CLUSTER_ENABLE_DELEGATION", False):
        logger.info("[Relay] Delegation disabled — relay loop not started")
        return

    interval = float(getattr(config, "CLUSTER_RELAY_POLL_INTERVAL_SECONDS", 5))
    relayed = _load_relayed()
    seeded = _RELAYED_FILE.exists()

    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        # First run: seed with whatever is already terminal so we don't spam the
        # room with a backlog of old results on initial startup.
        if not seeded:
            try:
                for task in await _list_terminal_tasks(client):
                    relayed.add(task["task_id"])
                _save_relayed(relayed)
                logger.info("[Relay] Seeded %d existing terminal task(s) as already-relayed", len(relayed))
            except Exception as exc:
                logger.warning("[Relay] Seed failed (%s) — will relay on next pass", exc)

        logger.info("[Relay] Watching for finished cluster tasks (interval=%ss)", interval)
        while True:
            await asyncio.sleep(interval)
            try:
                terminal = await _list_terminal_tasks(client)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[Relay] Poll failed: %s", exc)
                continue

            new_relays = False
            for summary in terminal:
                task_id = summary.get("task_id")
                if not task_id or task_id in relayed:
                    continue
                meta = summary.get("metadata") or {}
                room_id = meta.get("room_id")
                # Only relay Messenger-originated tasks that carry a room.
                if summary.get("source") != "messenger" or room_id is None:
                    relayed.add(task_id)  # not ours to deliver — mark and move on
                    new_relays = True
                    continue
                try:
                    full = await _load_full_task(client, task_id)
                    if not full:
                        relayed.add(task_id)
                        new_relays = True
                        continue
                    message = _format_message(full)
                    if message:
                        await send_fn(int(room_id), message)
                        logger.info("[Relay] Delivered task %s to room %s", task_id, room_id)
                    relayed.add(task_id)
                    new_relays = True
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # Leave it unmarked so we retry next pass.
                    logger.warning("[Relay] Failed to relay task %s: %s", task_id, exc)

            if new_relays:
                _save_relayed(relayed)
