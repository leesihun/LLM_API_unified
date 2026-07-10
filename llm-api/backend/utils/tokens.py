"""Lightweight, dependency-free token estimation and context budgeting.

Airgapped deployment — no tiktoken available. Tokens are approximated as
UTF-8 bytes // 3, which tracks Korean/CJK text (3 bytes/char ≈ 1–2 tokens)
far better than the naive char//4 heuristic. Used to bound the recent
conversation fed to the LLM to a fixed token budget across the stack.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def estimate_tokens(text: str) -> int:
    """Approximate the token count of *text* (UTF-8 bytes // 3)."""
    if not text:
        return 0
    return len(text.encode("utf-8")) // 3


def estimate_message_tokens(message: Dict[str, Any]) -> int:
    return estimate_tokens(str(message.get("content") or ""))


def total_message_tokens(messages: List[Dict[str, Any]]) -> int:
    return sum(estimate_message_tokens(m) for m in messages)


def trim_to_token_budget(
    messages: List[Dict[str, Any]],
    max_tokens: int,
    max_messages: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return the most-recent tail of *messages* fitting within *max_tokens*.

    Leading system messages are always preserved (their tokens are charged
    against the budget). Non-system messages are then kept newest-first until
    the token budget — or the optional *max_messages* count cap on non-system
    messages — is reached. At least one non-system message is always kept when
    any exist, even if it alone exceeds the budget.
    """
    if max_tokens <= 0:
        return list(messages)

    system_end = 0
    for i, m in enumerate(messages):
        if m.get("role") == "system":
            system_end = i + 1
        else:
            break
    system_msgs = messages[:system_end]
    rest = messages[system_end:]

    budget = max_tokens - total_message_tokens(system_msgs)
    kept_rev: List[Dict[str, Any]] = []
    used = 0
    for m in reversed(rest):
        if max_messages is not None and len(kept_rev) >= max_messages:
            break
        t = estimate_message_tokens(m)
        if kept_rev and used + t > budget:
            break
        kept_rev.append(m)
        used += t

    return system_msgs + list(reversed(kept_rev))
