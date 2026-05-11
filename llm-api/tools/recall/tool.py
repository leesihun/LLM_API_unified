"""ToolResultRecallTool: retrieve the full content of a previously truncated tool result."""
from pathlib import Path
from typing import Any, Dict

import config


class ToolResultRecallTool:
    """Read a tool result that was saved to disk when it exceeded its in-context budget."""

    def __init__(self, session_id: str = None):
        self.session_id = session_id

    def recall(self, tool_call_id: str, offset: int = 0, limit: int = 8000) -> Dict[str, Any]:
        if not self.session_id:
            return {"success": False, "error": "No active session — cannot locate saved results."}

        safe_id = tool_call_id.replace("/", "_").replace("\\", "_")[:64]
        path = config.TOOL_RESULTS_DIR / self.session_id / f"{safe_id}.json"

        if not path.exists():
            # Try a wildcard scan — the truncation marker may have used a slightly different id
            parent = config.TOOL_RESULTS_DIR / self.session_id
            if parent.is_dir():
                candidates = [f.name for f in parent.iterdir() if f.suffix == ".json"]
            else:
                candidates = []
            return {
                "success": False,
                "error": f"No saved result for tool_call_id '{tool_call_id}'.",
                "hint": f"Available results in this session: {candidates[:20]}",
            }

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return {"success": False, "error": f"Failed to read {path}: {e}"}

        total = len(content)
        chunk = content[offset: offset + limit]
        next_offset = offset + len(chunk)
        has_more = next_offset < total

        return {
            "success": True,
            "tool_call_id": tool_call_id,
            "content": chunk,
            "offset": offset,
            "limit": limit,
            "total_chars": total,
            "next_offset": next_offset if has_more else None,
            "has_more": has_more,
        }
