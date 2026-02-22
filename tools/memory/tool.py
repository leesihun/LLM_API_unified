"""
Memory Tool
Persistent key-value store scoped per user, persists across sessions.
Uses JSON file with FileLock for concurrency safety.
"""
import json
from pathlib import Path
from typing import Dict, Any, Optional

from filelock import FileLock

import config

MEMORY_DIR = Path("data/memory")
MEMORY_DIR.mkdir(parents=True, exist_ok=True)


class MemoryTool:
    """Per-user persistent key-value memory store."""

    def __init__(self, username: str):
        self.username = username
        self.store_path = MEMORY_DIR / f"{username}.json"
        self.lock_path = MEMORY_DIR / f"{username}.lock"

    def _load(self) -> Dict[str, str]:
        if self.store_path.exists():
            with open(self.store_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _save(self, data: Dict[str, str]):
        with open(self.store_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def execute(
        self,
        operation: str,
        key: Optional[str] = None,
        value: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Perform a memory operation.

        Args:
            operation: "set", "get", "delete", or "list"
            key: The key to operate on (required for set/get/delete)
            value: The value to store (required for set)
        """
        with FileLock(str(self.lock_path)):
            if operation == "set":
                if not key:
                    return {"success": False, "error": "Key is required for 'set' operation"}
                if value is None:
                    return {"success": False, "error": "Value is required for 'set' operation"}
                data = self._load()
                data[key] = value
                self._save(data)
                return {"success": True, "key": key, "stored": True}

            elif operation == "get":
                if not key:
                    return {"success": False, "error": "Key is required for 'get' operation"}
                data = self._load()
                if key in data:
                    return {"success": True, "key": key, "value": data[key]}
                return {"success": False, "error": f"Key not found: {key}"}

            elif operation == "delete":
                if not key:
                    return {"success": False, "error": "Key is required for 'delete' operation"}
                data = self._load()
                if key in data:
                    del data[key]
                    self._save(data)
                    return {"success": True, "key": key, "deleted": True}
                return {"success": False, "error": f"Key not found: {key}"}

            elif operation == "list":
                data = self._load()
                return {
                    "success": True,
                    "keys": list(data.keys()),
                    "count": len(data),
                }

            else:
                return {"success": False, "error": f"Unknown operation: {operation}. Use 'set', 'get', 'delete', or 'list'."}
