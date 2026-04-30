"""
File Editor Tool
Performs exact string replacements in existing files.
Surgical alternative to file_writer for modifying existing files.
"""
from pathlib import Path
from typing import Dict, Any, Optional

import config


class FileEditorTool:
    """Exact-string find-and-replace on files. Must read the file first."""

    def __init__(self, session_id: str = None, username: str = None):
        self.session_id = session_id
        self.username = username

    def _resolve_path(self, path: str) -> Path:
        """Resolve path using the same priority order as FileReaderTool."""
        target = Path(path).expanduser()
        if target.is_absolute():
            return target.resolve()

        if self.session_id:
            scratch_path = (config.SCRATCH_DIR / self.session_id / target).resolve()
            if scratch_path.exists():
                return scratch_path

        if self.username:
            upload_path = (config.UPLOAD_DIR / self.username / target).resolve()
            if upload_path.exists():
                return upload_path

        return (Path.cwd() / target).resolve()

    def edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> Dict[str, Any]:
        """
        Replace old_string with new_string in the file at path.

        Args:
            path: Absolute or session-relative path to the file.
            old_string: Exact text to find. Must be unique unless replace_all=True.
            new_string: Replacement text (can be empty string to delete).
            replace_all: If True, replace every occurrence. Default replaces only one.

        Returns:
            {"success": True, "path": str, "replacements": int}
            or {"success": False, "error": str}
        """
        target = self._resolve_path(path)

        if not target.exists():
            return {
                "success": False,
                "error": f"File not found: {target}",
            }

        if not target.is_file():
            return {
                "success": False,
                "error": f"Path is not a file: {target}",
            }

        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = target.read_text(encoding="utf-16")
            except Exception as exc:
                return {"success": False, "error": f"Cannot read file (encoding error): {exc}"}
        except Exception as exc:
            return {"success": False, "error": f"Cannot read file: {exc}"}

        count = content.count(old_string)

        if count == 0:
            return {
                "success": False,
                "error": (
                    f"old_string not found in file. "
                    "Ensure the text matches exactly (including whitespace and indentation). "
                    "Use file_reader to read the current file content first."
                ),
            }

        if count > 1 and not replace_all:
            return {
                "success": False,
                "error": (
                    f"old_string is not unique — found {count} occurrences. "
                    "Provide more surrounding context to make it unique, "
                    "or set replace_all=true to replace every occurrence."
                ),
            }

        if replace_all:
            new_content = content.replace(old_string, new_string)
            replacements = count
        else:
            new_content = content.replace(old_string, new_string, 1)
            replacements = 1

        try:
            target.write_text(new_content, encoding="utf-8")
        except Exception as exc:
            return {"success": False, "error": f"Cannot write file: {exc}"}

        return {
            "success": True,
            "path": str(target),
            "replacements": replacements,
        }
