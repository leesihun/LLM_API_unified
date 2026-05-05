"""
Agent package: single-while-loop agentic executor with native tool calling.

Public surface:
    AgentLoop   — the main class (import this)
    UnifiedAgent — backwards-compat alias for AgentLoop
"""
from backend.agent._cache import (
    _load_system_prompt,
    _build_tool_schemas,
    _CACHED_SYSTEM_PROMPT,
    _CACHED_TOOL_SCHEMAS,
    _rag_collections_cache,
    _RAG_CACHE_TTL,
    _memo_cache,
    _load_memo_cached,
)
from backend.agent.loop import AgentLoop

UnifiedAgent = AgentLoop  # backwards-compat alias (used in sessions.py)

__all__ = ["AgentLoop", "UnifiedAgent"]
