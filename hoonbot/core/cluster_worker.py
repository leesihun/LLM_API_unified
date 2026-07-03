"""Slave worker loop for master-owned cluster tasks."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from typing import Any

import httpx

import config
from core.context import build_llm_context

logger = logging.getLogger(__name__)

_TASK_EXECUTION_TEMPLATE = config.read_prompt("cluster/task_execution.txt")


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if config.CLUSTER_TOKEN:
        headers["x-cluster-token"] = config.CLUSTER_TOKEN
    return headers


def _node_payload() -> dict[str, Any]:
    disk = shutil.disk_usage(".")
    return {
        "node_name": config.NODE_NAME,
        "role": config.CLUSTER_ROLE,
        "ip": config.NODE_IP,
        "api_url": getattr(config, "LLM_API_URL", ""),
        "capabilities": config.NODE_CAPABILITIES,
        "tags": config.NODE_TAGS,
        "prompt_profile": getattr(config, "PROMPT_PROFILE", "slave"),
        "heartbeat_profile": getattr(config, "HEARTBEAT_PROFILE", "slave"),
        "skills_profile": getattr(config, "SKILLS_PROFILE", "slave"),
        "model": config.LLM_MODEL,
        "disk_free_gb": round(disk.free / 1e9, 1),
    }


async def _post(client: httpx.AsyncClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    resp = await client.post(
        f"{config.CLUSTER_MASTER_API_URL}{path}",
        headers=_headers(),
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()


async def _register(client: httpx.AsyncClient) -> None:
    await _post(client, "/api/cluster/register", _node_payload())
    logger.info("[Cluster] Registered node '%s' with master %s", config.NODE_NAME, config.CLUSTER_MASTER_API_URL)


async def _heartbeat(client: httpx.AsyncClient) -> None:
    payload = _node_payload()
    payload["heartbeat_at_monotonic"] = time.monotonic()
    await _post(client, "/api/cluster/heartbeat", payload)


async def _lease(client: httpx.AsyncClient) -> dict[str, Any] | None:
    result = await _post(client, "/api/cluster/tasks/lease", {
        "node_name": config.NODE_NAME,
        "capabilities": config.NODE_CAPABILITIES,
        "tags": config.NODE_TAGS,
    })
    return result.get("task")


async def _task_event(client: httpx.AsyncClient, task_id: str, message: str, event_type: str = "event") -> None:
    await _post(client, f"/api/cluster/tasks/{task_id}/events", {
        "node_name": config.NODE_NAME,
        "type": event_type,
        "message": message,
    })


async def _complete(client: httpx.AsyncClient, task_id: str, result: str | None = None, error: str | None = None) -> None:
    await _post(client, f"/api/cluster/tasks/{task_id}/complete", {
        "node_name": config.NODE_NAME,
        "status": "failed" if error else "completed",
        "result": result,
        "error": error,
    })


async def _execute_task(client: httpx.AsyncClient, task: dict[str, Any]) -> None:
    task_id = task["task_id"]
    prompt = task.get("prompt") or ""
    await _task_event(client, task_id, "Starting local LLM execution", "started")

    if not config.LLM_API_KEY:
        await _complete(client, task_id, error="LLM_API_KEY is not configured on slave")
        return
    if not config.LLM_MODEL:
        await _complete(client, task_id, error="LLM_MODEL is not configured on slave")
        return

    context = build_llm_context()
    task_prompt = _TASK_EXECUTION_TEMPLATE.format(
        task_id=task_id,
        node_name=config.NODE_NAME,
        prompt=prompt,
    )
    messages = [{
        "role": "user",
        "content": f"{context}\n\n---\n\n{task_prompt}",
    }]
    payload = {
        "model": config.LLM_MODEL,
        "messages": json.dumps(messages),
        "stream": "false",
        "session_id": f"cluster_{task_id}",
    }
    try:
        resp = await client.post(
            f"{config.LLM_API_URL}/v1/chat/completions",
            data=payload,
            headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
            timeout=config.LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data["choices"][0]["message"]["content"]
        await _complete(client, task_id, result=result)
        logger.info("[Cluster] Completed task %s (%s chars)", task_id, len(result))
    except Exception as exc:
        logger.error("[Cluster] Task %s failed: %s", task_id, exc, exc_info=True)
        await _complete(client, task_id, error=f"{type(exc).__name__}: {exc}")


async def run_slave_worker_loop() -> None:
    if not config.CLUSTER_ENABLED:
        logger.info("[Cluster] Disabled by config")
        return
    if config.CLUSTER_ROLE != "slave":
        logger.info("[Cluster] Worker loop skipped on role=%s", config.CLUSTER_ROLE)
        return

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=None), trust_env=False) as client:
        while True:
            try:
                await _register(client)
                break
            except Exception as exc:
                logger.warning("[Cluster] Register failed: %s", exc)
                await asyncio.sleep(config.CLUSTER_SLAVE_POLL_INTERVAL_SECONDS)

        running: set[asyncio.Task[None]] = set()

        def _on_task_done(done: asyncio.Task[None]) -> None:
            running.discard(done)
            if not done.cancelled() and done.exception() is not None:
                logger.error("[Cluster] Task runner crashed: %s", done.exception(), exc_info=done.exception())

        try:
            while True:
                try:
                    await _heartbeat(client)
                    # Fill free execution slots, then sleep; running tasks
                    # proceed in the background so the loop keeps polling.
                    while len(running) < config.CLUSTER_SLAVE_MAX_CONCURRENT_TASKS:
                        task = await _lease(client)
                        if not task:
                            break
                        runner = asyncio.create_task(
                            _execute_task(client, task),
                            name=f"cluster-task-{task['task_id']}",
                        )
                        running.add(runner)
                        runner.add_done_callback(_on_task_done)
                    await asyncio.sleep(config.CLUSTER_SLAVE_POLL_INTERVAL_SECONDS)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("[Cluster] Worker loop error: %s", exc)
                    await asyncio.sleep(config.CLUSTER_SLAVE_POLL_INTERVAL_SECONDS)
        finally:
            for runner in running:
                runner.cancel()
            if running:
                await asyncio.gather(*running, return_exceptions=True)
