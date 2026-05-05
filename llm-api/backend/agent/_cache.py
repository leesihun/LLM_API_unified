"""Module-level prompt, schema, RAG, and memo caches shared across agent submodules."""
from typing import List, Dict, Any

import config


def _load_system_prompt() -> str:
    prompt_path = config.PROMPTS_DIR / config.AGENT_SYSTEM_PROMPT
    if prompt_path.exists():
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    return "You are a helpful assistant with access to tools."


def _build_tool_schemas() -> List[Dict[str, Any]]:
    """Build tool schemas once at module load. Frozen order for cache stability."""
    from tools.schemas import TOOL_SCHEMAS
    schemas = []
    for tool_name in config.AVAILABLE_TOOLS:
        schema = TOOL_SCHEMAS.get(tool_name)
        if not schema:
            continue
        params = dict(schema["parameters"])
        props = dict(params.get("properties", {}))
        required = list(params.get("required", []))
        props.pop("session_id", None)
        if "session_id" in required:
            required.remove("session_id")
        schemas.append({
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema["description"],
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        })
    return schemas


_CACHED_SYSTEM_PROMPT: str = _load_system_prompt()
_CACHED_TOOL_SCHEMAS: List[Dict[str, Any]] = _build_tool_schemas()

# {username: {"collections": [...], "expires_at": float}}
_rag_collections_cache: Dict[str, Dict[str, Any]] = {}
_RAG_CACHE_TTL: float = 60.0

# {username: (mtime_float, content_str)}
_memo_cache: Dict[str, tuple] = {}


def _load_memo_cached(username: str) -> str:
    """Return MemoTool.load_for_prompt() result, re-reading only when the file changes."""
    from tools.memo.tool import MemoTool
    memo_path = config.MEMO_DIR / f"{username}.json"
    try:
        mtime = memo_path.stat().st_mtime
        cached = _memo_cache.get(username)
        if cached and cached[0] == mtime:
            return cached[1]
        content = MemoTool.load_for_prompt(username)
        _memo_cache[username] = (mtime, content)
        return content
    except FileNotFoundError:
        _memo_cache[username] = (0.0, "")
        return ""
    except Exception:
        # Fallback to uncached read on any unexpected error
        from tools.memo.tool import MemoTool as _MemoTool
        return _MemoTool.load_for_prompt(username)
