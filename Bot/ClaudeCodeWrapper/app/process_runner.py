import asyncio
import json
import logging
import shutil
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Process tracker: maintains instance context per workspace
# ---------------------------------------------------------------------------

class ProcessTracker:
    """Tracks which workspace has an active instance to avoid unnecessary restarts."""

    def __init__(self):
        self._last_workspace: str | None = None
        self._workspace_changed = False

    def update_workspace(self, workspace: str) -> bool:
        """
        Update the current workspace and return True if it changed.
        This allows the caller to reuse context if the workspace is the same.
        """
        changed = workspace != self._last_workspace
        if changed:
            self._last_workspace = workspace
            logger.info(f"Workspace changed to: {workspace}")
        else:
            logger.debug(f"Workspace unchanged: {workspace} (reusing context)")
        return changed

    def get_current_workspace(self) -> str | None:
        return self._last_workspace


_tracker = ProcessTracker()


async def run_cli(
    command: str,
    prompt: str,
    workspace: str,
    timeout: int,
    on_output: Callable[[str], Awaitable[None]],
    allowed_tools: list[str] | None = None,
    skip_permissions: bool = False,
) -> dict:
    """
    Spawn a CLI process for the given prompt.
    If the workspace hasn't changed since the last task, the running instance
    will maintain its context (working directory, environment, etc.).

    Returns {"exit_code": int, "output": str} or includes "error" on failure.
    """
    executable = shutil.which(command)
    if not executable:
        error_msg = f"Command not found: {command}"
        logger.error(error_msg)
        return {"exit_code": -1, "output": "", "error": error_msg}

    # Track workspace changes
    workspace_changed = _tracker.update_workspace(workspace)

    args = [executable, "-p", prompt, "--output-format", "stream-json", "--verbose"]

    if skip_permissions:
        args.append("--dangerously-skip-permissions")
    elif allowed_tools:
        args.append("--allowedTools")
        args.extend(allowed_tools)

    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=workspace,
    )

    full_output: list[str] = []

    try:
        await asyncio.wait_for(
            _read_stream(process, on_output, full_output),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(f"Process timed out after {timeout}s")
        process.terminate()
        await process.wait()
        return {
            "exit_code": -1,
            "output": "".join(full_output),
            "error": f"Task timed out after {timeout}s",
        }
    except asyncio.CancelledError:
        logger.debug("Process cancelled")
        process.terminate()
        await process.wait()
        raise

    stderr_bytes = await process.stderr.read()
    await process.wait()

    stderr_text = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
    if stderr_text:
        logger.debug(f"stderr: {stderr_text.strip()}")

    result: dict = {
        "exit_code": process.returncode,
        "output": "".join(full_output),
    }
    if process.returncode != 0 and stderr_text:
        result["error"] = stderr_text.strip()
    return result


# ---------------------------------------------------------------------------
# Stream reader
# ---------------------------------------------------------------------------

async def _read_stream(
    process: asyncio.subprocess.Process,
    on_output: Callable[[str], Awaitable[None]],
    accumulator: list[str],
) -> None:
    """Read stdout line-by-line, parse stream-json, and forward text chunks."""
    buffer = ""
    while True:
        chunk = await process.stdout.read(4096)
        if not chunk:
            break
        buffer += chunk.decode("utf-8", errors="replace")

        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            stripped = line.strip()
            if stripped:
                logger.debug(f"stdout: {stripped}")
            text = _parse_line(stripped)
            if text:
                accumulator.append(text)
                await on_output(text)

    if buffer.strip():
        text = _parse_line(buffer.strip())
        if text:
            accumulator.append(text)
            await on_output(text)


# ---------------------------------------------------------------------------
# Stream-JSON parsing
# ---------------------------------------------------------------------------

def _parse_line(line: str) -> str:
    if not line:
        return ""
    try:
        data = json.loads(line)
        return _extract_text(data)
    except json.JSONDecodeError:
        return line


def _extract_text(data) -> str:
    if isinstance(data, str):
        return data
    if not isinstance(data, dict):
        return ""

    for key in ("text", "content", "result", "output"):
        val = data.get(key)
        if isinstance(val, str):
            return val
        if isinstance(val, list):
            return "".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in val
            )

    if "message" in data and isinstance(data["message"], dict):
        return _extract_text(data["message"])

    if "delta" in data and isinstance(data["delta"], dict):
        return _extract_text(data["delta"])

    return ""
