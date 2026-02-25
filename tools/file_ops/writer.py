"""
File Writer Tool
Write or append content to files.
Lightweight alternative to python_coder for simple file creation.
"""
from pathlib import Path
from typing import Dict, Any

class FileWriterTool:
    """Write files to the local filesystem."""

    def __init__(self, session_id: str):
        self.session_id = session_id

    def _resolve_target(self, path: str) -> Path:
        """
        Resolve file path for write operations.

        Absolute paths are used directly.
        Relative paths are resolved from the current working directory.
        """
        target_path = Path(path).expanduser()
        if target_path.is_absolute():
            return target_path.resolve()
        return (Path.cwd() / target_path).resolve()

    def write(
        self,
        path: str,
        content: str,
        mode: str = "write",
    ) -> Dict[str, Any]:
        """
        Write or append content to a file.

        Args:
            path: Absolute path or path relative to current working directory
            content: Text content to write
            mode: "write" (overwrite) or "append"
        """
        if mode not in {"write", "append"}:
            raise ValueError(f"Unsupported mode: {mode}. Use 'write' or 'append'.")
        target = self._resolve_target(path)

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
