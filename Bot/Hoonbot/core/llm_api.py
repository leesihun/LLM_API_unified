"""Shared HTTP client for Hoonbot -> LLM API requests."""
from typing import Optional

import httpx

import config

_client: Optional[httpx.AsyncClient] = None


def get_client() -> httpx.AsyncClient:
    """Return the shared LLM API client."""
    global _client
    if _client is None or _client.is_closed:
        timeout = float(config.LLM_TIMEOUT_SECONDS)
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
            trust_env=False,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _client


async def close_client() -> None:
    """Close the shared LLM API client."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None
