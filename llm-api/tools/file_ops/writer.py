"""
File Writer Tool
Write or append content to files.

Newly-created files are tracked in the response (`new_file: True`) so the
agent loop can sweep non-persisted temp files at the end of a session.
"""
from pathlib import Path
from typing import Dict, Any, Optional

import config


class FileWriterTool:
    """Write files to the local filesystem."""

    def __init__(self, session_id: str, workspace_dir: Optional[Path] = None):
        self.session_id = session_id or "default"
        self.workspace_dir = Path(workspace_dir).resolve() if workspace_dir else None
        # Default base for relative paths: workspace_dir if set, else server CWD.
        self.workspace = self.workspace_dir or Path.cwd()

    def _resolve_target(self, path: str) -> Path:
        target_path = Path(path).expanduser()
        if target_path.is_absolute():
            resolved = target_path.resolve()
        else:
            resolved = (self.workspace / target_path).resolve()

        allowed = [d.resolve() for d in config.ALLOWED_WRITE_DIRS]
        if allowed and not any(resolved.is_relative_to(a) for a in allowed):
            allowed_str = ", ".join(str(a) for a in allowed)
            raise PermissionError(
                f"Path '{resolved}' is outside allowed write directories. "
                f"Allowed: {allowed_str}."
            )
        return resolved

    def write(
        self,
        path: str,
        content: str,
        mode: str = "write",
        persist: bool = False,
    ) -> Dict[str, Any]:
        """Write or append content to a file.

        Args:
            path: Absolute path, or relative path resolved against the
                  session workspace (workspace_dir if set, else server CWD).
            content: Text content to write.
            mode: 'write' (overwrite) or 'append'.
            persist: If False (default), a newly-created file is treated as
                     temporary and will be deleted at session end. Set True
                     when the file is a deliverable the user asked for.
        """
        if mode not in {"write", "append"}:
            raise ValueError(f"Unsupported mode: {mode}. Use 'write' or 'append'.")
        target = self._resolve_target(path)
        is_new = not target.exists()

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
            "new_file": is_new,
            "persist": bool(persist),
        }
