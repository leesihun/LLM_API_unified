"""
V4A apply_patch tool — context-anchored diff format used by Codex CLI and Claude Code.

Unlike traditional unified diffs (--- +++ @@ line-numbers), V4A locates edit
regions by matching surrounding context lines, making it robust against line
shifts and tolerant of CRLF/whitespace differences common in .ps1 files.

Format:
    *** Begin Patch
    *** Add File: path/to/new.py
    +new line 1
    +new line 2
    *** Delete File: path/to/old.py
    *** Update File: path/to/existing.py
    @@ optional locator text
     unchanged context line
    -removed line
    +added line
     unchanged context line
    *** Move to: path/to/new-name.py
    *** End Patch

Multi-file patches (any mix of Add/Delete/Update/Move) are supported in one envelope.

Matching strategy (applied in order until one succeeds):
    Tier 1 — Exact match
    Tier 2 — Match ignoring line endings (CRLF vs LF)
    Tier 3 — Match ignoring all trailing whitespace per line
    Tier 4 — Tab expansion (try 4, 2, 8 stops) on both sides
On failure, returns an actionable error naming the anchor line that failed.
"""
import difflib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import config

_GENERATED_PARTS = {".git", "__pycache__", "data", "dist", "dist-web", "node_modules"}


class ApplyPatchTool:
    """Apply V4A context-anchored patches to files."""

    def __init__(self, session_id: str = None, username: str = None,
                 workspace_dir: Optional[Path] = None):
        self.session_id = session_id
        self.username = username
        self.workspace_dir = Path(workspace_dir).resolve() if workspace_dir else None
        # Workspace, when set, becomes the project root. Falls back to the
        # API's repo root for legacy behaviour.
        self.repo_root = self.workspace_dir or config.APP_DIR.parent.resolve()

    # ------------------------------------------------------------------ #
    # Path resolution                                                       #
    # ------------------------------------------------------------------ #

    def _resolve_path(self, raw: str, must_exist: bool = True) -> Path:
        p = Path(raw.strip()).expanduser()
        resolved = p.resolve() if p.is_absolute() else (self.repo_root / p).resolve()

        allowed = [d.resolve() for d in getattr(config, "ALLOWED_WRITE_DIRS", [])]
        if allowed:
            if not any(resolved.is_relative_to(base) for base in allowed):
                allowed_str = ", ".join(str(b) for b in allowed)
                raise PermissionError(f"Path outside allowed dirs: {resolved}. Allowed: {allowed_str}")
        elif not resolved.is_relative_to(self.repo_root):
            raise PermissionError(f"Path outside repository root: {resolved}")

        try:
            rel_parts = resolved.relative_to(self.repo_root).parts
            if any(part in _GENERATED_PARTS for part in rel_parts):
                raise PermissionError(f"Refusing to patch generated/runtime path: {resolved}")
        except ValueError:
            pass

        if must_exist and not resolved.exists():
            raise FileNotFoundError(f"File not found: {resolved}")
        return resolved

    # ------------------------------------------------------------------ #
    # BOM / line-ending detection                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _detect_file_meta(raw_bytes: bytes) -> Tuple[bool, str]:
        """Return (has_bom, dominant_line_ending: '\\r\\n' or '\\n')."""
        has_bom = raw_bytes[:3] == b"\xef\xbb\xbf"
        sample = raw_bytes[:4096]
        crlf = sample.count(b"\r\n")
        lf = sample.count(b"\n") - crlf
        dominant = "\r\n" if crlf >= lf else "\n"
        return has_bom, dominant

    # ------------------------------------------------------------------ #
    # V4A patch parser                                                      #
    # ------------------------------------------------------------------ #

    def _parse_v4a(self, patch: str) -> List[Dict[str, Any]]:
        """Parse a V4A patch envelope into a list of file operations."""
        lines = patch.splitlines()

        # Find envelope boundaries
        try:
            begin = next(i for i, l in enumerate(lines) if l.strip() == "*** Begin Patch")
            end = next(i for i, l in enumerate(lines) if l.strip() == "*** End Patch")
        except StopIteration:
            raise ValueError(
                "V4A patch must start with '*** Begin Patch' and end with '*** End Patch'."
            )

        ops: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None
        current_hunk_lines: List[str] = []

        def _flush_hunk():
            if current is not None and current_hunk_lines:
                current["hunks"].append(list(current_hunk_lines))
                current_hunk_lines.clear()

        for raw in lines[begin + 1:end]:
            stripped = raw.strip()

            if stripped.startswith("*** Add File:"):
                _flush_hunk()
                if current:
                    ops.append(current)
                current = {
                    "op": "add",
                    "path": stripped[len("*** Add File:"):].strip(),
                    "hunks": [],
                }
                current_hunk_lines.clear()

            elif stripped.startswith("*** Delete File:"):
                _flush_hunk()
                if current:
                    ops.append(current)
                current = {
                    "op": "delete",
                    "path": stripped[len("*** Delete File:"):].strip(),
                    "hunks": [],
                }
                current_hunk_lines.clear()

            elif stripped.startswith("*** Update File:"):
                _flush_hunk()
                if current:
                    ops.append(current)
                current = {
                    "op": "update",
                    "path": stripped[len("*** Update File:"):].strip(),
                    "move_to": None,
                    "hunks": [],
                }
                current_hunk_lines.clear()

            elif stripped.startswith("*** Move to:"):
                if current and current["op"] == "update":
                    _flush_hunk()
                    current["move_to"] = stripped[len("*** Move to:"):].strip()
                    current_hunk_lines.clear()

            elif stripped.startswith("@@"):
                # @@ marks the start of a new hunk (context anchor in header)
                _flush_hunk()
                if current:
                    # Store anchor text for error messages
                    current_hunk_lines.append(raw)

            elif current is not None and raw and raw[0] in {" ", "-", "+"}:
                current_hunk_lines.append(raw)

        _flush_hunk()
        if current:
            ops.append(current)

        if not ops:
            raise ValueError(
                "No file operations found. Use '*** Add File:', '*** Delete File:', "
                "or '*** Update File:' directives inside the envelope."
            )
        return ops

    # ------------------------------------------------------------------ #
    # Context-anchored matching (4-tier)                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _norm_endings(lines: List[str]) -> List[str]:
        return [l.rstrip("\r\n") for l in lines]

    @staticmethod
    def _norm_trailing(lines: List[str]) -> List[str]:
        return [l.rstrip() for l in lines]

    @staticmethod
    def _expand_tabs(line: str, stops: int) -> str:
        return line.expandtabs(stops)

    def _find_context_match(
        self, file_lines: List[str], context_lines: List[str], anchor: str
    ) -> Optional[int]:
        """Return the start index of context_lines in file_lines, or None.

        Tries 4 normalization tiers in order.
        """
        if not context_lines:
            return 0

        def _search(f_lines: List[str], c_lines: List[str]) -> Optional[int]:
            n = len(c_lines)
            for i in range(len(f_lines) - n + 1):
                if f_lines[i:i + n] == c_lines:
                    return i
            return None

        # Tier 1: exact
        idx = _search(file_lines, context_lines)
        if idx is not None:
            return idx

        # Tier 2: ignore line endings (CRLF vs LF)
        f2 = self._norm_endings(file_lines)
        c2 = self._norm_endings(context_lines)
        idx = _search(f2, c2)
        if idx is not None:
            return idx

        # Tier 3: ignore trailing whitespace
        f3 = self._norm_trailing(f2)
        c3 = self._norm_trailing(c2)
        idx = _search(f3, c3)
        if idx is not None:
            return idx

        # Tier 4: tab expansion (4, 2, 8 stops)
        for stops in (4, 2, 8):
            f4 = [self._expand_tabs(l, stops) for l in f3]
            c4 = [self._expand_tabs(l, stops) for l in c3]
            idx = _search(f4, c4)
            if idx is not None:
                return idx

        return None

    # ------------------------------------------------------------------ #
    # Hunk application                                                      #
    # ------------------------------------------------------------------ #

    def _apply_hunk(
        self, file_lines: List[str], hunk_lines: List[str]
    ) -> Tuple[List[str], int]:
        """Apply one hunk to file_lines. Returns (new_lines, start_index).
        Raises ValueError with an actionable message on mismatch."""
        # Separate @@ anchor line from context/diff lines
        anchor = ""
        body = []
        for raw in hunk_lines:
            if raw.strip().startswith("@@"):
                anchor = raw.strip()
            elif raw and raw[0] in {" ", "-", "+"}:
                body.append(raw)

        # Extract context lines (space-prefixed) and removal lines (minus-prefixed)
        context = [l[1:] for l in body if l[0] == " "]
        removals = [l[1:] for l in body if l[0] == "-"]

        # Build the search block: context + removals in order (the "old" file fragment)
        search_lines: List[str] = []
        for raw in body:
            if raw[0] in {" ", "-"}:
                search_lines.append(raw[1:])

        if not search_lines:
            # Pure-insertion hunk with no context — append to end
            new_lines = body  # only + lines
            additions = [l[1:] for l in new_lines if l and l[0] == "+"]
            return file_lines + additions, len(file_lines)

        start = self._find_context_match(file_lines, search_lines, anchor)
        if start is None:
            anchor_display = anchor or (search_lines[0][:60] if search_lines else "?")
            raise ValueError(
                f"Error: Invalid Context: {anchor_display}\n"
                "The context lines in this hunk do not match the current file content. "
                "Use file_reader to read the current file, then regenerate the hunk "
                "with context lines that exactly match (whitespace may differ slightly, "
                "but leading indentation must match)."
            )

        end = start + len(search_lines)
        # Build replacement: keep context lines, drop removals, insert additions
        replacement: List[str] = []
        src_idx = start
        for raw in body:
            if raw[0] == " ":
                # Context: preserve original line verbatim (normalisation was for search only)
                replacement.append(file_lines[src_idx])
                src_idx += 1
            elif raw[0] == "-":
                src_idx += 1  # skip
            elif raw[0] == "+":
                replacement.append(raw[1:])

        return file_lines[:start] + replacement + file_lines[end:], start

    # ------------------------------------------------------------------ #
    # File-level operations                                                 #
    # ------------------------------------------------------------------ #

    def _apply_update(self, path_str: str, hunks: List[List[str]]) -> str:
        target = self._resolve_path(path_str, must_exist=True)
        raw_bytes = target.read_bytes()
        has_bom, dominant_ending = self._detect_file_meta(raw_bytes)

        # Decode: strip BOM for processing
        payload = raw_bytes.lstrip(b"\xef\xbb\xbf") if has_bom else raw_bytes
        text = payload.decode("utf-8", errors="replace")

        file_lines = text.splitlines(keepends=True)

        for hunk in hunks:
            file_lines, _ = self._apply_hunk(file_lines, hunk)

        # Reconstruct: normalize all line endings to dominant_ending, restore BOM
        result_lines = []
        for line in file_lines:
            stripped = line.rstrip("\r\n")
            result_lines.append(stripped + dominant_ending)

        result_text = "".join(result_lines)
        result_bytes = result_text.encode("utf-8")
        if has_bom:
            result_bytes = b"\xef\xbb\xbf" + result_bytes

        target.write_bytes(result_bytes)
        return str(target)

    def _apply_add(self, path_str: str, hunks: List[List[str]]) -> str:
        target = self._resolve_path(path_str, must_exist=False)
        if target.exists():
            raise FileExistsError(f"Add File: target already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for hunk in hunks:
            for raw in hunk:
                if raw and raw[0] == "+":
                    lines.append(raw[1:])
        target.write_text("".join(lines), encoding="utf-8")
        return str(target)

    def _apply_delete(self, path_str: str) -> str:
        target = self._resolve_path(path_str, must_exist=True)
        target.unlink()
        return str(target)

    def _apply_move(self, path_str: str, move_to: str, hunks: List[List[str]]) -> str:
        # Apply any hunks to the old path first, then rename
        if hunks:
            self._apply_update(path_str, hunks)
        src = self._resolve_path(path_str, must_exist=True)
        dst = self._resolve_path(move_to, must_exist=False)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        return str(dst)

    # ------------------------------------------------------------------ #
    # Diff generation for success output                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _make_diff(before: str, after: str, path: str) -> str:
        diff = list(difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        ))
        return "".join(diff[:120]) if diff else "(no textual changes)"

    # ------------------------------------------------------------------ #
    # Public entry point                                                    #
    # ------------------------------------------------------------------ #

    def apply(self, patch: str) -> Dict[str, Any]:
        """Apply a V4A patch envelope. Returns success dict or error dict."""
        try:
            ops = self._parse_v4a(patch)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        changed: List[Dict[str, Any]] = []
        for op in ops:
            try:
                op_type = op["op"]
                path_str = op["path"]

                if op_type == "add":
                    out = self._apply_add(path_str, op["hunks"])
                    changed.append({"op": "added", "path": out})

                elif op_type == "delete":
                    out = self._apply_delete(path_str)
                    changed.append({"op": "deleted", "path": out})

                elif op_type == "update":
                    if op.get("move_to"):
                        # Read before-state for diff, then update+move
                        try:
                            t = self._resolve_path(path_str)
                            before = t.read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8", errors="replace")
                        except Exception:
                            before = ""
                        out = self._apply_move(path_str, op["move_to"], op["hunks"])
                        after = Path(out).read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8", errors="replace")
                        diff = self._make_diff(before, after, out)
                        changed.append({"op": "moved+updated", "path": out, "diff": diff})
                    else:
                        t = self._resolve_path(path_str)
                        before = t.read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8", errors="replace")
                        out = self._apply_update(path_str, op["hunks"])
                        after = Path(out).read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8", errors="replace")
                        diff = self._make_diff(before, after, path_str)
                        changed.append({"op": "updated", "path": out, "diff": diff})

            except (ValueError, FileNotFoundError, PermissionError, FileExistsError) as exc:
                return {"success": False, "error": str(exc)}
            except Exception as exc:
                return {"success": False, "error": f"Unexpected error on {op.get('path', '?')}: {exc}"}

        return {"success": True, "files_changed": changed}
