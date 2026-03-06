"""
Memo Tool — persistent key-value memory across sessions.

Stores named facts in data/memory/{username}.json.
Entries are injected into the agent system prompt automatically,
giving the LLM continuity across conversations.
"""
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

import config

_lock = threading.Lock()


class MemoTool:
    """Read/write persistent per-user memory entries."""

    def __init__(self, username: str):
        self.username = username or "guest"
        self.memo_file = config.MEMO_DIR / f"{self.username}.json"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def execute(
        self,
        operation: str,
        key: Optional[str] = None,
        value: Optional[str] = None,
    ) -> Dict[str, Any]:
        if operation == "write":
            return self._write(key, value)
        elif operation == "read":
            return self._read(key)
        elif operation == "list":
            return self._list()
        elif operation == "delete":
            return self._delete(key)
        else:
            return {"success": False, "error": f"Unknown operation: {operation}. Use write/read/list/delete."}

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def _write(self, key: Optional[str], value: Optional[str]) -> Dict[str, Any]:
        if not key:
            return {"success": False, "error": "key is required for write operation."}
        if value is None:
            return {"success": False, "error": "value is required for write operation."}

        key = key.strip()
        if not key:
            return {"success": False, "error": "key cannot be empty."}

        if len(value) > config.MEMO_MAX_VALUE_LENGTH:
            value = value[:config.MEMO_MAX_VALUE_LENGTH]

        with _lock:
            data = self._load()
            if len(data) >= config.MEMO_MAX_ENTRIES and key not in data:
                return {
                    "success": False,
                    "error": f"Memory is full ({config.MEMO_MAX_ENTRIES} entries). Delete an entry first.",
                }
            data[key] = {
                "value": value,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            self._save(data)

        return {"success": True, "key": key, "written": True}

    def _read(self, key: Optional[str]) -> Dict[str, Any]:
        if not key:
            return {"success": False, "error": "key is required for read operation."}

        with _lock:
            data = self._load()

        entry = data.get(key.strip())
        if entry is None:
            return {"success": False, "error": f"No memo entry found for key '{key}'."}

        return {
            "success": True,
            "key": key,
            "value": entry["value"],
            "updated_at": entry.get("updated_at", ""),
        }

    def _list(self) -> Dict[str, Any]:
        with _lock:
            data = self._load()

        entries = [
            {"key": k, "value": v["value"], "updated_at": v.get("updated_at", "")}
            for k, v in data.items()
        ]
        return {"success": True, "entries": entries, "count": len(entries)}

    def _delete(self, key: Optional[str]) -> Dict[str, Any]:
        if not key:
            return {"success": False, "error": "key is required for delete operation."}

        key = key.strip()
        with _lock:
            data = self._load()
            if key not in data:
                return {"success": False, "error": f"No memo entry found for key '{key}'."}
            del data[key]
            self._save(data)

        return {"success": True, "key": key, "deleted": True}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load(self) -> Dict[str, Any]:
        """Load memo data from disk. Returns empty dict if file doesn't exist."""
        if not self.memo_file.exists():
            return {}
        try:
            return json.loads(self.memo_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, data: Dict[str, Any]):
        """Save memo data to disk."""
        self.memo_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Static helper used by agent to inject memo into system prompt
    # ------------------------------------------------------------------

    @staticmethod
    def load_for_prompt(username: str) -> str:
        """
        Return a formatted string of memo entries to inject into the system prompt.
        Returns empty string if no entries exist.
        """
        memo_file = config.MEMO_DIR / f"{username or 'guest'}.json"
        if not memo_file.exists():
            return ""

        try:
            data = json.loads(memo_file.read_text(encoding="utf-8"))
        except Exception:
            return ""

        if not data:
            return ""

        lines = ["\n\n## PERSISTENT MEMORY",
                 "The following facts were saved from previous sessions:"]
        for key, entry in data.items():
            updated = entry.get("updated_at", "")
            updated_str = f" (saved {updated})" if updated else ""
            lines.append(f"- {key}: {entry['value']}{updated_str}")

        return "\n".join(lines)
