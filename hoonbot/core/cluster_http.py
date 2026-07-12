"""Shared HTTP helpers for talking to the master's /api/cluster endpoints."""
from __future__ import annotations

from typing import Any

import httpx

import config


def cluster_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if getattr(config, "CLUSTER_TOKEN", ""):
        headers["x-cluster-token"] = config.CLUSTER_TOKEN
    return headers


def master_url(path: str) -> str:
    return f"{config.CLUSTER_MASTER_API_URL}{path}"


async def post_json(client: httpx.AsyncClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    resp = await client.post(master_url(path), headers=cluster_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()


async def get_json(client: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = await client.get(master_url(path), params=params, headers=cluster_headers())
    resp.raise_for_status()
    return resp.json()
