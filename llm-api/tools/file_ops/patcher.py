"""
Contextual unified-diff patch tool for existing text files.

This is intentionally small and conservative: it applies ordinary ---/+++
unified-diff hunks only when the old context matches the current file exactly.
"""
import re
from pathlib import Path
from typing import Any, Dict, List

import config


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_GENERATED_PARTS = {
    ".git",
    "__pycache__",
    "data",
    "dist",
    "dist-web",
    "node_modules",
}


class FilePatchTool:
    """Apply unified-diff patches to existing text files."""

    def __init__(self, session_id: str = None, username: str = None):
        self.session_id = session_id
        self.username = username
        self.repo_root = config.APP_DIR.parent.resolve()

    def _clean_diff_path(self, raw_path: str) -> str:
        path = raw_path.strip()
        if "\t" in path:
            path = path.split("\t", 1)[0]
        if " " in path:
            path = path.split(" ", 1)[0]
        if path in {"/dev/null", "NUL"}:
            raise ValueError("file_patch only modifies existing files; create/delete patches are rejected.")
        if path.startswith("a/") or path.startswith("b/"):
            path = path[2:]
        return path.replace("\\", "/")

    def _resolve_target(self, raw_path: str) -> Path:
        path = self._clean_diff_path(raw_path)
        target = Path(path).expanduser()
        resolved = target.resolve() if target.is_absolute() else (self.repo_root / target).resolve()

        allowed = [d.resolve() for d in config.ALLOWED_WRITE_DIRS]
        if allowed:
            if not any(resolved.is_relative_to(base) for base in allowed):
                allowed_str = ", ".join(str(base) for base in allowed)
                raise PermissionError(f"Patch target is outside allowed write directories: {resolved}. Allowed: {allowed_str}")
        elif not resolved.is_relative_to(self.repo_root):
            raise PermissionError(f"Patch target is outside repository root: {resolved}")

        rel_parts = resolved.relative_to(self.repo_root).parts if resolved.is_relative_to(self.repo_root) else resolved.parts
        if any(part in _GENERATED_PARTS for part in rel_parts):
            raise PermissionError(f"Refusing to patch generated/runtime path: {resolved}")

        if not resolved.exists():
            raise FileNotFoundError(f"Patch target does not exist: {resolved}")
        if not resolved.is_file():
            raise ValueError(f"Patch target is not a file: {resolved}")
        if b"\x00" in resolved.read_bytes()[:8192]:
            raise ValueError(f"Refusing to patch binary-looking file: {resolved}")
        return resolved

    def _parse_patch(self, patch: str) -> List[Dict[str, Any]]:
        lines = patch.splitlines(keepends=True)
        files: List[Dict[str, Any]] = []
        i = 0
        while i < len(lines):
            if not lines[i].startswith("--- "):
                i += 1
                continue

            old_path = lines[i][4:].strip()
            i += 1
            if i >= len(lines) or not lines[i].startswith("+++ "):
                raise ValueError("Malformed patch: expected +++ header after --- header.")
            new_path = lines[i][4:].strip()
            i += 1

            hunks = []
            while i < len(lines) and not lines[i].startswith("--- "):
                match = _HUNK_RE.match(lines[i])
                if not match:
                    i += 1
                    continue
                old_start = int(match.group(1))
                i += 1
                body = []
                while i < len(lines) and not lines[i].startswith("@@ ") and not lines[i].startswith("--- "):
                    line = lines[i]
                    if line.startswith("\\ No newline at end of file"):
                        i += 1
                        continue
                    if not line or line[0] not in {" ", "-", "+"}:
                        raise ValueError(f"Malformed hunk line: {line[:80]!r}")
                    body.append(line)
                    i += 1
                hunks.append({"old_start": old_start, "body": body})

            files.append({"old_path": old_path, "new_path": new_path, "hunks": hunks})

        if not files:
            raise ValueError("No unified-diff file headers found. Include ---/+++ headers and @@ hunks.")
        return files

    def _same_line(self, file_line: str, patch_line: str) -> bool:
        return file_line.rstrip("\r\n") == patch_line.rstrip("\r\n")

    def _with_file_newline(self, text: str, newline: str) -> str:
        if text.endswith("\r\n"):
            return text[:-2] + newline
        if text.endswith("\n"):
            return text[:-1] + newline
        return text

    def _apply_hunks(self, target: Path, hunks: List[Dict[str, Any]]) -> int:
        original = target.read_text(encoding="utf-8")
        file_lines = original.splitlines(keepends=True)
        newline = "\r\n" if "\r\n" in original else "\n"
        offset = 0
        replacements = 0

        for hunk in hunks:
            index = hunk["old_start"] - 1 + offset
            if index < 0 or index > len(file_lines):
                raise ValueError(f"Hunk starts outside file: {target}")

            cursor = index
            replacement = []
            for raw in hunk["body"]:
                kind = raw[0]
                content = self._with_file_newline(raw[1:], newline)
                if kind in {" ", "-"}:
                    if cursor >= len(file_lines) or not self._same_line(file_lines[cursor], content):
                        raise ValueError(
                            f"Patch context does not match current file at {target}:{cursor + 1}. "
                            "Re-read the file and regenerate the patch."
                        )
                    if kind == " ":
                        replacement.append(file_lines[cursor])
                    cursor += 1
                if kind == "+":
                    replacement.append(content)

            file_lines[index:cursor] = replacement
            offset += len(replacement) - (cursor - index)
            replacements += 1

        target.write_text("".join(file_lines), encoding="utf-8")
        return replacements

    def apply(self, patch: str) -> Dict[str, Any]:
        try:
            parsed_files = self._parse_patch(patch)
            changed = []
            for file_patch in parsed_files:
                if not file_patch["hunks"]:
                    raise ValueError(f"No hunks found for {file_patch['new_path']}")
                if self._clean_diff_path(file_patch["old_path"]) != self._clean_diff_path(file_patch["new_path"]):
                    raise ValueError("file_patch does not support renames or path-changing patches.")
                target = self._resolve_target(file_patch["new_path"])
                hunks_applied = self._apply_hunks(target, file_patch["hunks"])
                changed.append({"path": str(target), "hunks_applied": hunks_applied})
            return {
                "success": True,
                "files_changed": changed,
            }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
            }
