"""
File Editor Tool
Performs exact string replacements in existing files, with a fuzzy-fallback
chain (line-trimmed -> indent-flexible -> whitespace-collapsed) so a one-space
or tab-vs-space mismatch in `old_string` doesn't kill the edit.
"""
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import config


class FileEditorTool:
    """Exact-string find-and-replace on files with progressive fuzzy fallback."""

    def __init__(self, session_id: str = None, username: str = None,
                 workspace_dir: Optional[Path] = None):
        self.session_id = session_id
        self.username = username
        self.workspace_dir = Path(workspace_dir).resolve() if workspace_dir else None

    def _resolve_path(self, path: str) -> Path:
        """Resolve relative paths against workspace_dir, then user uploads,
        then server CWD. Absolute paths are used directly."""
        target = Path(path).expanduser()
        if target.is_absolute():
            return target.resolve()

        if self.workspace_dir:
            ws_path = (self.workspace_dir / target).resolve()
            if ws_path.exists():
                return ws_path

        if self.username:
            upload_path = (config.UPLOAD_DIR / self.username / target).resolve()
            if upload_path.exists():
                return upload_path

        base = self.workspace_dir or getattr(config, "AGENT_DEFAULT_WORKSPACE", None) or Path.cwd()
        return (Path(base) / target).resolve()

    def edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> Dict[str, Any]:
        """
        Replace old_string with new_string in the file at path.

        Tries an exact byte-level match first. If that fails, falls back to
        line-block matching with progressively looser whitespace normalisation.
        The returned `strategy` field reports which match succeeded so logs
        reveal when the model's old_string drifted from the file.

        Args:
            path: Absolute or session-relative path to the file.
            old_string: Text to find.
            new_string: Replacement text (can be empty to delete).
            replace_all: Replace every exact occurrence (fuzzy strategies
                         always require a unique match).
        """
        target = self._resolve_path(path)

        if not target.exists():
            return {"success": False, "error": f"File not found: {target}"}
        if not target.is_file():
            return {"success": False, "error": f"Path is not a file: {target}"}

        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = target.read_text(encoding="utf-16")
            except Exception as exc:
                return {"success": False, "error": f"Cannot read file (encoding error): {exc}"}
        except Exception as exc:
            return {"success": False, "error": f"Cannot read file: {exc}"}

        exact_count = content.count(old_string)

        if exact_count >= 1:
            if exact_count > 1 and not replace_all:
                return {
                    "success": False,
                    "error": (
                        f"old_string is not unique - found {exact_count} occurrences. "
                        "Provide more surrounding context to make it unique, "
                        "or set replace_all=true to replace every occurrence."
                    ),
                }
            if replace_all:
                new_content = content.replace(old_string, new_string)
                replacements = exact_count
            else:
                new_content = content.replace(old_string, new_string, 1)
                replacements = 1
            return self._commit(target, new_content, replacements, "exact")

        # Fuzzy fallback: try progressively looser whitespace normalisations.
        # Each strategy must find exactly one line-block match.
        for strategy_name, normalizer in _STRATEGIES:
            fuzzy = _try_fuzzy_block(content, old_string, new_string, normalizer)
            if fuzzy is not None:
                new_content, replacements = fuzzy
                return self._commit(target, new_content, replacements, strategy_name)

        return {
            "success": False,
            "error": (
                "old_string not found in file (exact match failed and all "
                "fuzzy strategies failed or produced ambiguous matches). "
                "Re-read the file with file_reader and retry with a smaller, "
                "more precisely-anchored old_string."
            ),
        }

    def _commit(self, target: Path, new_content: str, replacements: int,
                strategy: str) -> Dict[str, Any]:
        try:
            target.write_text(new_content, encoding="utf-8")
        except Exception as exc:
            return {"success": False, "error": f"Cannot write file: {exc}"}
        return {
            "success": True,
            "path": str(target),
            "replacements": replacements,
            "strategy": strategy,
        }


# ---------------------------------------------------------------------------
# Fuzzy line-block matching
# ---------------------------------------------------------------------------

_INDENT_SIGIL = "\x01"  # control char, never appears in source code


def _norm_line_trimmed(line: str) -> str:
    """Strip trailing whitespace (including \\r and line terminators)."""
    return line.rstrip()


def _norm_indent_flexible(line: str) -> str:
    """Normalise leading whitespace (tabs <-> spaces) while preserving its
    presence. Trailing whitespace is also stripped."""
    stripped = line.rstrip()
    lstripped = stripped.lstrip()
    if len(lstripped) < len(stripped):
        return _INDENT_SIGIL + lstripped
    return lstripped


_WS_RUN = re.compile(r"\s+")


def _norm_whitespace_collapsed(line: str) -> str:
    """Collapse runs of whitespace to single space, then strip."""
    return _WS_RUN.sub(" ", line).strip()


_STRATEGIES: List[Tuple[str, Callable[[str], str]]] = [
    ("line-trimmed", _norm_line_trimmed),
    ("indent-flexible", _norm_indent_flexible),
    ("whitespace-collapsed", _norm_whitespace_collapsed),
]


def _try_fuzzy_block(
    content: str,
    old_string: str,
    new_string: str,
    normalizer: Callable[[str], str],
) -> Optional[Tuple[str, int]]:
    """Try to locate old_string as a contiguous line-block in content under
    the given normaliser. Returns (new_content, replacements) on a unique
    match, None otherwise.

    Only works when old_string spans one or more whole lines after
    normalisation. Mid-line partial matches are out of scope for fuzzy
    fallback - the model should re-read and use a more precise anchor."""
    content_lines = content.splitlines(keepends=True)
    old_lines = old_string.splitlines(keepends=True)
    if not old_lines or not content_lines:
        return None

    norm_content = [normalizer(line) for line in content_lines]
    norm_old = [normalizer(line) for line in old_lines]

    n = len(norm_old)
    starts: List[int] = []
    for i in range(len(norm_content) - n + 1):
        if norm_content[i:i + n] == norm_old:
            starts.append(i)

    if len(starts) != 1:
        return None

    start = starts[0]

    # Preserve the trailing-newline shape of the last replaced line so we
    # don't accidentally join the following line onto the replacement.
    last_replaced = content_lines[start + n - 1]
    if last_replaced.endswith("\r\n"):
        tail = "\r\n"
    elif last_replaced.endswith("\n"):
        tail = "\n"
    else:
        tail = ""

    new_block = new_string.rstrip("\r\n") + tail

    result = (
        "".join(content_lines[:start])
        + new_block
        + "".join(content_lines[start + n:])
    )
    return result, 1
