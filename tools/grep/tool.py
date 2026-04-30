"""
Grep Tool
Content search using ripgrep (rg) with a pure-Python fallback.
Mirrors OpenClaude's GrepTool parameter surface exactly.
"""
import fnmatch
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


_RG_BIN: Optional[str] = shutil.which("rg")


class GrepTool:
    """
    Fast content search. Uses ripgrep when available, pure-Python otherwise.
    Results default to files_with_matches (paths only). Use output_mode='content'
    to see matching lines with context.
    """

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #

    def search(
        self,
        pattern: str,
        path: Optional[str] = None,
        glob: Optional[str] = None,
        output_mode: str = "files_with_matches",
        context: int = 0,
        before: int = 0,
        after: int = 0,
        case_insensitive: bool = False,
        file_type: Optional[str] = None,
        head_limit: int = 250,
        offset: int = 0,
        multiline: bool = False,
    ) -> Dict[str, Any]:
        """
        Search file contents for pattern.

        Args:
            pattern:          Regex to search for.
            path:             Directory or file to search (default: cwd).
            glob:             Glob filter, e.g. "*.py" or "*.{ts,tsx}".
            output_mode:      "files_with_matches" | "content" | "count".
            context:          Lines of context around each match (rg -C).
            before:           Lines before each match (rg -B).
            after:            Lines after each match (rg -A).
            case_insensitive: Case-insensitive search (rg -i).
            file_type:        Ripgrep file type filter, e.g. "py", "js".
            head_limit:       Cap output at N lines/entries (default 250; 0=unlimited).
            offset:           Skip first N entries before applying head_limit.
            multiline:        Match across newlines (rg -U --multiline-dotall).
        """
        search_path = Path(path).resolve() if path else Path.cwd()

        if _RG_BIN:
            return self._rg_search(
                pattern, search_path, glob, output_mode, context, before, after,
                case_insensitive, file_type, head_limit, offset, multiline,
            )
        return self._py_search(
            pattern, search_path, glob, output_mode, context, before, after,
            case_insensitive, head_limit, offset, multiline,
        )

    # ------------------------------------------------------------------ #
    # Ripgrep backend
    # ------------------------------------------------------------------ #

    def _rg_search(
        self,
        pattern: str,
        search_path: Path,
        glob: Optional[str],
        output_mode: str,
        context: int,
        before: int,
        after: int,
        case_insensitive: bool,
        file_type: Optional[str],
        head_limit: int,
        offset: int,
        multiline: bool,
    ) -> Dict[str, Any]:
        args: List[str] = [_RG_BIN, "--hidden"]

        # Exclude common VCS dirs
        for vcs in (".git", ".svn", ".hg", ".bzr"):
            args += ["--glob", f"!{vcs}"]

        args += ["--max-columns", "500"]

        if multiline:
            args += ["-U", "--multiline-dotall"]

        if case_insensitive:
            args.append("-i")

        # Output mode flags
        if output_mode == "files_with_matches":
            args.append("-l")
        elif output_mode == "count":
            args.append("-c")
        else:  # content
            args.append("-n")  # line numbers
            if context:
                args += ["-C", str(context)]
            elif before or after:
                if before:
                    args += ["-B", str(before)]
                if after:
                    args += ["-A", str(after)]

        if file_type:
            args += ["--type", file_type]
        if glob:
            args += ["--glob", glob]

        # Pattern (prefix with -e if it starts with a dash)
        if pattern.startswith("-"):
            args += ["-e", pattern]
        else:
            args.append(pattern)

        args.append(str(search_path))

        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "grep timed out after 30s", "results": "", "num_matches": 0, "truncated": False}
        except Exception as exc:
            return {"success": False, "error": f"rg error: {exc}", "results": "", "num_matches": 0, "truncated": False}

        raw_lines = proc.stdout.splitlines()

        # Relativize paths
        cwd = Path.cwd()
        relativized = []
        for line in raw_lines:
            try:
                p = Path(line)
                if p.is_absolute():
                    line = str(p.relative_to(cwd))
            except (ValueError, OSError):
                pass
            relativized.append(line)

        # Apply offset + head_limit
        if offset:
            relativized = relativized[offset:]
        truncated = False
        if head_limit and len(relativized) > head_limit:
            relativized = relativized[:head_limit]
            truncated = True

        result_str = "\n".join(relativized)
        num_matches = len(relativized)

        return {
            "success": True,
            "results": result_str,
            "num_matches": num_matches,
            "truncated": truncated,
            "engine": "ripgrep",
        }

    # ------------------------------------------------------------------ #
    # Pure-Python fallback
    # ------------------------------------------------------------------ #

    def _py_search(
        self,
        pattern: str,
        search_path: Path,
        glob: Optional[str],
        output_mode: str,
        context: int,
        before: int,
        after: int,
        case_insensitive: bool,
        head_limit: int,
        offset: int,
        multiline: bool,
    ) -> Dict[str, Any]:
        flags = re.IGNORECASE if case_insensitive else 0
        if multiline:
            flags |= re.DOTALL

        try:
            compiled = re.compile(pattern, flags)
        except re.error as exc:
            return {"success": False, "error": f"Invalid regex: {exc}", "results": "", "num_matches": 0, "truncated": False}

        # Collect files
        files = self._collect_files(search_path, glob)

        output_lines: List[str] = []
        cwd = Path.cwd()

        for fpath in files:
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            if output_mode == "files_with_matches":
                if compiled.search(text):
                    try:
                        rel = str(fpath.relative_to(cwd))
                    except ValueError:
                        rel = str(fpath)
                    output_lines.append(rel)

            elif output_mode == "count":
                count = len(compiled.findall(text))
                if count:
                    try:
                        rel = str(fpath.relative_to(cwd))
                    except ValueError:
                        rel = str(fpath)
                    output_lines.append(f"{rel}: {count}")

            else:  # content
                lines = text.splitlines()
                ctx_before = max(context, before)
                ctx_after = max(context, after)
                matched_indices = set()
                for i, line in enumerate(lines):
                    if compiled.search(line):
                        matched_indices.add(i)

                if not matched_indices:
                    continue

                try:
                    rel = str(fpath.relative_to(cwd))
                except ValueError:
                    rel = str(fpath)

                shown = set()
                for idx in sorted(matched_indices):
                    start = max(0, idx - ctx_before)
                    end = min(len(lines), idx + ctx_after + 1)
                    for j in range(start, end):
                        if j not in shown:
                            output_lines.append(f"{rel}:{j+1}: {lines[j]}")
                            shown.add(j)

        # Apply offset + head_limit
        if offset:
            output_lines = output_lines[offset:]
        truncated = False
        if head_limit and len(output_lines) > head_limit:
            output_lines = output_lines[:head_limit]
            truncated = True

        return {
            "success": True,
            "results": "\n".join(output_lines),
            "num_matches": len(output_lines),
            "truncated": truncated,
            "engine": "python-fallback",
        }

    def _collect_files(self, root: Path, glob_pattern: Optional[str]) -> List[Path]:
        """Walk root and collect files matching optional glob pattern."""
        skip_dirs = {".git", ".svn", ".hg", "__pycache__", "node_modules", ".venv", "venv"}
        files: List[Path] = []

        if root.is_file():
            return [root]

        for dirpath, dirnames, filenames in os.walk(root):
            # Prune skipped dirs in-place
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for fname in filenames:
                fpath = Path(dirpath) / fname
                if glob_pattern:
                    if not fnmatch.fnmatch(fname, glob_pattern):
                        continue
                try:
                    if fpath.stat().st_size > 10 * 1024 * 1024:  # skip files > 10 MB
                        continue
                except OSError:
                    continue
                files.append(fpath)

        # Sort by mtime desc, then alpha
        files.sort(key=lambda f: (-f.stat().st_mtime if f.exists() else 0, str(f)))
        return files
