"""Retry helper with exponential backoff for async functions."""
import asyncio
import logging
from typing import Tuple, Type

import httpx

logger = logging.getLogger(__name__)

RETRYABLE = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
)


def _is_retryable(exc: BaseException, retryable: tuple) -> bool:
    """Check if an exception is worth retrying (includes 5xx HTTP errors)."""
    if isinstance(exc, retryable):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500:
        return True
    return False


async def with_retry(
    coro_fn,
    *args,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    retryable: Tuple[Type[BaseException], ...] = RETRYABLE,
    label: str = "",
    **kwargs,
):
    """
    Call an async function with exponential backoff on transient failures.
    Also retries HTTP 5xx errors.

    Usage:
        result = await with_retry(some_async_fn, arg1, arg2, label="LLM chat")
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await coro_fn(*args, **kwargs)
        except Exception as exc:
            if not _is_retryable(exc, retryable):
                raise
            last_exc = exc
            if attempt == max_attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                f"[Retry] {label or coro_fn.__name__} attempt {attempt}/{max_attempts} "
                f"failed ({type(exc).__name__}), retrying in {delay:.1f}s"
            )
            await asyncio.sleep(delay)

    logger.error(f"[Retry] {label or coro_fn.__name__} failed after {max_attempts} attempts")
    raise last_exc
