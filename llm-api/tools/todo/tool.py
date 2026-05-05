"""
Todo Tool
Session-scoped task checklist. Stateless — list is stored on AgentLoop.
Mirrors OpenClaude's TodoWriteTool: write the full list each call.
"""
from typing import Any, Dict, List

_VALID_STATUSES = {"pending", "in_progress", "completed"}
_VALID_PRIORITIES = {"high", "medium", "low"}


class TodoTool:
    """
    Validates and returns a full todo list replacement.
    The AgentLoop stores the list and injects it into dynamic context.
    """

    def write(self, todos: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Replace the session todo list with the provided list.

        Each todo must have:
            id       (str)  — stable identifier
            content  (str)  — imperative description, e.g. "Fix auth bug"
            status   (str)  — "pending" | "in_progress" | "completed"
            priority (str)  — "high" | "medium" | "low"

        At most ONE item may be "in_progress" at a time.
        """
        if not isinstance(todos, list):
            return {"success": False, "error": "todos must be a list"}

        validated: List[Dict[str, Any]] = []
        in_progress_count = 0

        for i, item in enumerate(todos):
            if not isinstance(item, dict):
                return {"success": False, "error": f"todos[{i}] must be an object"}

            todo_id = str(item.get("id", f"task_{i+1}"))
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            priority = str(item.get("priority", "medium")).lower()

            if not content:
                return {"success": False, "error": f"todos[{i}].content must not be empty"}
            if status not in _VALID_STATUSES:
                return {"success": False, "error": f"todos[{i}].status must be one of {sorted(_VALID_STATUSES)}, got '{status}'"}
            if priority not in _VALID_PRIORITIES:
                return {"success": False, "error": f"todos[{i}].priority must be one of {sorted(_VALID_PRIORITIES)}, got '{priority}'"}

            if status == "in_progress":
                in_progress_count += 1
                if in_progress_count > 1:
                    return {"success": False, "error": "At most one task may be 'in_progress' at a time"}

            validated.append({
                "id": todo_id,
                "content": content,
                "status": status,
                "priority": priority,
            })

        all_done = validated and all(t["status"] == "completed" for t in validated)

        return {
            "success": True,
            "todos": validated,
            "count": len(validated),
            "all_completed": all_done,
        }
