"""Master-side helper for delegating Messenger requests to cluster nodes."""

from __future__ import annotations

import re
from typing import Any

import httpx

import config


_DIRECTIVE_RE = re.compile(r"^\s*@([A-Za-z0-9_.:-]+)\s*(.*)$", re.DOTALL)
_RESERVED = {"bot", "clear", "compact"}


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if config.CLUSTER_TOKEN:
        headers["x-cluster-token"] = config.CLUSTER_TOKEN
    return headers


async def _post(client: httpx.AsyncClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    resp = await client.post(
        f"{config.CLUSTER_MASTER_API_URL}{path}",
        headers=_headers(),
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()


async def _get_nodes(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    resp = await client.get(f"{config.CLUSTER_MASTER_API_URL}/api/cluster/nodes", headers=_headers())
    resp.raise_for_status()
    return list(resp.json().get("nodes") or [])


async def try_submit_from_message(content: str, sender_name: str, room_id: int) -> dict[str, Any] | None:
    """Return delegation summary when content starts with a cluster directive."""
    if not getattr(config, "CLUSTER_ENABLE_DELEGATION", False):
        return None

    match = _DIRECTIVE_RE.match(content)
    if not match:
        return None

    directive = match.group(1).strip()
    prompt = match.group(2).strip()
    if not prompt:
        return None

    lowered = directive.lower()
    if lowered in _RESERVED or lowered == config.MESSENGER_BOT_NAME.lower():
        return None

    created_by = f"messenger:{sender_name}:room:{room_id}"

    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        if lowered == "all-slaves":
            nodes = await _get_nodes(client)
            targets = [
                node["node_name"]
                for node in nodes
                if node.get("role") == "slave" and node.get("healthy", True)
            ]
            task_ids = []
            for node_name in targets:
                result = await _post(client, "/api/cluster/tasks", {
                    "prompt": prompt,
                    "target_node": node_name,
                    "source": "messenger",
                    "created_by": created_by,
                    "metadata": {"room_id": room_id, "directive": directive},
                })
                task_ids.append(result["task"]["task_id"])
            return {
                "kind": "broadcast",
                "message": f"Queued {len(task_ids)} cluster task(s) for @all-slaves: {', '.join(task_ids) or 'no healthy slaves'}",
            }

        body: dict[str, Any] = {
            "prompt": prompt,
            "source": "messenger",
            "created_by": created_by,
            "metadata": {"room_id": room_id, "directive": directive},
        }
        if lowered.startswith("tag:"):
            body["required_tags"] = [directive.split(":", 1)[1]]
        elif lowered.startswith("role:"):
            body["required_tags"] = [directive.split(":", 1)[1]]
        else:
            body["target_node"] = directive

        result = await _post(client, "/api/cluster/tasks", body)
        task = result["task"]
        target = task.get("target_node") or ",".join(task.get("required_tags") or task.get("required_capabilities") or [])
        return {
            "kind": "task",
            "task_id": task["task_id"],
            "message": f"Queued cluster task {task['task_id']} for @{target}.",
        }
