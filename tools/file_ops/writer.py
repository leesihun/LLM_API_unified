"""
File Writer Tool
Write or append content to files in the scratch workspace.
Lightweight alternative to python_coder for simple file creation.
"""
from pathlib import Path
from typing import Dict, Any

import config


class FileWriterTool:
    """Write files to the session scratch workspace."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.workspace = config.SCRATCH_DIR / session_id
        self.workspace.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        path: str,
        content: str,
        mode: str = "write",
    ) -> Dict[str, Any]:
        """
        Write or append content to a file.

        Args:
            path: File path relative to scratch workspace
            content: Text content to write
            mode: "write" (overwrite) or "append"
        """
        target = (self.workspace / path).resolve()

        # Security: ensure target is within workspace
        if not str(target).startswith(str(self.workspace.resolve())):
            raise PermissionError("Access denied: path escapes workspace")

        target.parent.mkdir(parents=True, exist_ok=True)

        if mode == "append":
            with open(target, 'a', encoding='utf-8') as f:
                f.write(content)
        else:
            with open(target, 'w', encoding='utf-8') as f:
                f.write(content)

        bytes_written = len(content.encode('utf-8'))

        return {
            "success": True,
            "path": str(target),
            "bytes_written": bytes_written,
            "mode": mode,
        }
