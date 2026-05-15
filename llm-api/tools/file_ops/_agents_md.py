"""
Walk up from a tool-accessed path collecting unseen AGENTS.md / CLAUDE.md files.

Each one is injected into the tool result so the model sees subtree-specific
instructions when it actually reaches into that subtree, rather than only
seeing the workspace-root AGENTS.md at session start. Per-session de-dup is
maintained on the agent instance.
"""
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


INSTRUCTION_FILENAMES = ("AGENTS.md", "CLAUDE.md")
_PER_FILE_CAP = 8192


def walk_up_for_agents_md(
    accessed_path: Path,
    workspace_root: Path,
    seen: Set[str],
) -> List[Tuple[Path, str]]:
    """Walk parents from accessed_path up to (and including) workspace_root.

    Returns the new (path, content) pairs discovered on this call and adds
    their resolved-str keys to *seen*. Caller is responsible for persisting
    *seen* across tool calls in the same session.
    """
    try:
        accessed = Path(accessed_path).resolve()
        root = Path(workspace_root).resolve()
    except Exception:
        return []

    if accessed.is_dir():
        current = accessed
    else:
        current = accessed.parent

    if not current.exists():
        return []

    # Stop walking above workspace root; if accessed is outside the root,
    # walk only up to filesystem root (bounded by parent==current loop).
    try:
        within_root = root in current.parents or current == root
    except Exception:
        within_root = False

    discovered: List[Tuple[Path, str]] = []
    while True:
        for filename in INSTRUCTION_FILENAMES:
            candidate = current / filename
            try:
                if not candidate.is_file():
                    continue
                key = str(candidate.resolve())
                if key in seen:
                    continue
                seen.add(key)
                content = candidate.read_text(encoding="utf-8", errors="replace")
                if len(content) > _PER_FILE_CAP:
                    content = content[:_PER_FILE_CAP] + "\n...[AGENTS.md truncated]"
                discovered.append((candidate, content))
            except (OSError, PermissionError):
                continue

        if within_root and current == root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
        if within_root:
            try:
                within_root = root in current.parents or current == root
            except Exception:
                within_root = False
            if not within_root:
                break

    return discovered


def attach_to_result(
    result: Dict[str, Any],
    discovered: List[Tuple[Path, str]],
) -> None:
    """Add discovered AGENTS.md files to *result* under a stable key the LLM
    will surface when the result is JSON-serialised. Mutates in place."""
    if not discovered:
        return
    result["instructions_from_subtree"] = [
        {"path": str(path), "content": content}
        for path, content in discovered
    ]
