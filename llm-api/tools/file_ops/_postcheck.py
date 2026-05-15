"""
Post-edit syntax verification for files touched by file_writer / file_edit /
apply_patch. The agent loop calls check_python() on every successful write to a
.py file; failures are attached to the tool result dict so the model sees them
in the next turn and self-repairs before declaring done.

v1 covers Python only via `python -m py_compile`. TS/JS would need a
project-aware tsc runner and is deferred.
"""
import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional


_POSTCHECK_TIMEOUT_S = 5


def _run_py_compile(path: str) -> Dict[str, Any]:
    """Blocking py_compile invocation. Run via asyncio.to_thread()."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "py_compile", path],
            capture_output=True,
            text=True,
            timeout=_POSTCHECK_TIMEOUT_S,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"status": "failed", "error": "py_compile timed out (>5s)"}
    except Exception as exc:
        return {"status": "skipped", "error": f"py_compile invocation error: {exc}"}

    if proc.returncode == 0:
        return {"status": "passed"}
    return {
        "status": "failed",
        "error": (proc.stderr or proc.stdout or "py_compile failed without output").strip(),
    }


async def check_python(path: str) -> Dict[str, Any]:
    """Async wrapper around py_compile. Returns:
        {"status": "passed"}
        {"status": "failed", "error": "<stderr>"}
        {"status": "skipped", "error": "..."}
    Always returns a dict; never raises.
    """
    try:
        if not Path(path).is_file():
            return {"status": "skipped", "error": "file not found after edit"}
    except Exception as exc:
        return {"status": "skipped", "error": str(exc)}
    return await asyncio.to_thread(_run_py_compile, path)


def is_python_path(path: Optional[str]) -> bool:
    if not path:
        return False
    return path.lower().endswith(".py")
