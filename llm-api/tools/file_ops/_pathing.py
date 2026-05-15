"""
Shared path-resolution helpers for file_ops tools.

When a relative path doesn't resolve, the tool should return enough information
for the model to self-correct on the next turn — not just "file not found".

This module provides:
- candidate_roots():  ordered list of (label, Path) roots to try
- near_matches():     basenames within Levenshtein <= max_distance of a target
- deepest_ancestor(): deepest existing directory along a non-resolving path
- build_failure_report(): assembled structured failure dict
"""
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

import config


_SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules",
    ".venv", "venv", "env", "dist", "dist-web", "build",
    ".pytest_cache", ".mypy_cache", "data",
}


def candidate_roots(
    workspace_dir: Optional[Path],
    username: Optional[str] = None,
) -> List[Tuple[str, Path]]:
    """Ordered list of roots a relative path is tried against.

    The order matches the resolution order in FileReaderTool._resolve_path:
    workspace -> user uploads -> cwd. Each entry is (label, Path).
    """
    roots: List[Tuple[str, Path]] = []
    if workspace_dir:
        roots.append(("workspace", Path(workspace_dir).resolve()))
    if username:
        try:
            roots.append(("uploads", (config.UPLOAD_DIR / username).resolve()))
        except Exception:
            pass
    default_root = workspace_dir or getattr(config, "AGENT_DEFAULT_WORKSPACE", None) or Path.cwd()
    roots.append(("default", Path(default_root).resolve()))
    return roots


def _bounded_levenshtein(a: str, b: str, max_distance: int) -> int:
    """Levenshtein with early exit. Returns max_distance+1 when exceeded."""
    la, lb = len(a), len(b)
    if abs(la - lb) > max_distance:
        return max_distance + 1
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i] + [0] * lb
        row_min = curr[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
            if curr[j] < row_min:
                row_min = curr[j]
        if row_min > max_distance:
            return max_distance + 1
        prev = curr
    return prev[lb]


def near_matches(
    basename: str,
    search_root: Path,
    max_distance: int = 2,
    max_depth: int = 3,
    cap: int = 10,
) -> List[str]:
    """Return up to *cap* file paths whose basename is within Levenshtein
    *max_distance* of *basename*. Walks at most *max_depth* levels below
    *search_root*, skipping VCS / build / cache directories.

    Returned paths are relative to *search_root* when possible, otherwise
    absolute. Case-insensitive comparison.
    """
    if not search_root.is_dir():
        return []
    target = basename.casefold()
    root_parts = len(search_root.parts)
    matches: List[Tuple[int, str]] = []

    try:
        for path in search_root.rglob("*"):
            if not path.is_file():
                continue
            depth = len(path.parts) - root_parts - 1
            if depth > max_depth:
                continue
            if any(part in _SKIP_DIRS for part in path.parts[root_parts:-1]):
                continue
            name = path.name.casefold()
            dist = _bounded_levenshtein(target, name, max_distance)
            if dist <= max_distance:
                try:
                    rel = str(path.relative_to(search_root))
                except ValueError:
                    rel = str(path)
                matches.append((dist, rel))
                if len(matches) >= cap * 4:
                    break
    except (PermissionError, OSError):
        pass

    matches.sort(key=lambda pair: (pair[0], pair[1]))
    return [path for _, path in matches[:cap]]


def deepest_ancestor(requested: Path) -> Tuple[Optional[Path], List[str]]:
    """Walk up *requested* until an existing directory is found. Return
    (ancestor, top_entries). ancestor is None if no part of the path exists
    (rare — root usually exists). top_entries is up to 10 sorted entries
    of that directory, dirs suffixed with '/'."""
    current = requested
    while current and not current.exists():
        parent = current.parent
        if parent == current:
            return None, []
        current = parent
    if not current.is_dir():
        return current, []
    try:
        entries = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        formatted = [
            f"{p.name}/" if p.is_dir() else p.name
            for p in entries[:10]
        ]
        return current, formatted
    except (PermissionError, OSError):
        return current, []


def build_failure_report(
    requested: str,
    attempted: List[Path],
    workspace_dir: Optional[Path],
    error: str = "file not found",
) -> Dict[str, Any]:
    """Assemble the structured failure dict that gets returned to the agent.

    Includes attempted_paths, near_matches (scanned from workspace or cwd),
    and parent_listing of the deepest existing ancestor of the last attempt.
    """
    attempted_strs = [str(p) for p in attempted]

    requested_basename = Path(requested).name
    if workspace_dir:
        search_root = Path(workspace_dir).resolve()
    else:
        search_root = Path(
            getattr(config, "AGENT_DEFAULT_WORKSPACE", None) or Path.cwd()
        ).resolve()
    near = near_matches(requested_basename, search_root) if requested_basename else []

    ancestor: Optional[Path] = None
    entries: List[str] = []
    for candidate in reversed(attempted):
        ancestor, entries = deepest_ancestor(candidate)
        if ancestor is not None:
            break

    report: Dict[str, Any] = {
        "success": False,
        "error": error,
        "requested": requested,
        "attempted_paths": attempted_strs,
    }
    if near:
        report["near_matches"] = near
    if ancestor is not None:
        report["parent_listing"] = {
            "path": str(ancestor),
            "entries": entries,
        }
    return report
