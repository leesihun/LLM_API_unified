"""Shared HTTP client for Hoonbot -> LLM API requests."""
from typing import Optional

import httpx

import config

_client: Optional[httpx.AsyncClient] = None


def get_client() -> httpx.AsyncClient:
    """Return the shared LLM API client."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            # read=1800 (30 min per chunk) is generous enough for OpenCode startup
            # and slow shell tools while still letting a truly stuck stream surface
            # as ReadTimeout — read=None blocks the heartbeat loop forever when the
            # llm-api server degrades after many requests.
            timeout=httpx.Timeout(connect=10.0, read=1800.0, write=60.0, pool=60.0),
            trust_env=False,
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
                keepalive_expiry=30.0,
            ),
        )
    return _client


async def close_client() -> None:
    """Close the shared LLM API client."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None
