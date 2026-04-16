"""
Shell Execution Tool
Run shell commands via async subprocess with incremental output streaming.

Output is drained chunk-by-chunk as the process runs — once MAX_OUTPUT_SIZE is
reached we stop storing further bytes but keep reading so the process never
blocks on a full pipe. On timeout, partial output collected so far is still
available (the shared buffer holds everything streamed up to that moment).
"""
import asyncio
import time
from pathlib import Path
from typing import Dict, Any, Optional

import config

MAX_OUTPUT_SIZE = 50 * 1024  # 50KB cap per stream
_READ_CHUNK = 4096

# Track already-created workspace directories to skip redundant mkdir calls
_created_dirs: set = set()


async def _drain_into(
    stream: asyncio.StreamReader,
    buf: bytearray,
    max_bytes: int,
) -> None:
    """Drain *stream* into *buf*, capping stored bytes at max_bytes.

    Keeps reading past the cap so the writing process never blocks on a full
    pipe. Excess bytes are dropped. Appends a "[truncated]" marker once.
    """
    truncated = False
    while True:
        chunk = await stream.read(_READ_CHUNK)
        if not chunk:
            return
        if truncated:
            continue
        room = max_bytes - len(buf)
        if room > 0:
            buf.extend(chunk[:room])
        if len(buf) >= max_bytes and not truncated:
            buf.extend(b"\n...[truncated]")
            truncated = True


def _decode(buf: bytearray) -> str:
    return bytes(buf).decode('utf-8', errors='replace')


class ShellExecTool:
    """Execute shell commands via async subprocess with incremental streaming."""

    def __init__(self, session_id: str):
        self.session_id = session_id or "default"
        self.workspace = config.SCRATCH_DIR / self.session_id
        if self.session_id not in _created_dirs:
            self.workspace.mkdir(parents=True, exist_ok=True)
            _created_dirs.add(self.session_id)

    def _resolve_working_directory(self, working_directory: Optional[str]) -> Path:
        """
        Resolve working directory for command execution.

        Absolute paths are used directly.
        Relative paths are resolved from the session scratch workspace.
        If unset, default to session workspace for compatibility.
        """
        if not working_directory:
            return self.workspace.resolve()

        cwd = Path(working_directory).expanduser()
        if cwd.is_absolute():
            return cwd.resolve()
        return (self.workspace / cwd).resolve()

    async def execute(
        self,
        command: str,
        timeout: int = 300,
        working_directory: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a shell command asynchronously with streaming output drain.

        On timeout:
        - SHELL_EXEC_KILL_ON_TIMEOUT=True (default): kill the process, return
          whatever was streamed so far.
        - False: leave the process running, return partial output + live PID.
        """
        cwd = self._resolve_working_directory(working_directory)
        cwd.mkdir(parents=True, exist_ok=True)

        start = time.time()
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
            )
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "duration": round(time.time() - start, 2),
                "command": command,
            }

        stdout_buf = bytearray()
        stderr_buf = bytearray()
        stdout_task = asyncio.create_task(_drain_into(proc.stdout, stdout_buf, MAX_OUTPUT_SIZE))
        stderr_task = asyncio.create_task(_drain_into(proc.stderr, stderr_buf, MAX_OUTPUT_SIZE))

        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            duration = time.time() - start
            kill_on_timeout = getattr(config, "SHELL_EXEC_KILL_ON_TIMEOUT", True)

            if kill_on_timeout:
                # Kill → pipes close → drain tasks finish cleanly
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                return {
                    "success": False,
                    "killed": True,
                    "error": f"Process killed after {timeout}s timeout",
                    "stdout": _decode(stdout_buf),
                    "stderr": _decode(stderr_buf),
                    "duration": round(duration, 2),
                    "command": command,
                    "pid": proc.pid,
                }

            # Legacy mode: process still running — snapshot current buffers, cancel drains
            stdout_task.cancel()
            stderr_task.cancel()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            return {
                "success": False,
                "still_running": True,
                "error": f"Process still running after {timeout}s",
                "stdout": _decode(stdout_buf),
                "stderr": _decode(stderr_buf),
                "duration": round(duration, 2),
                "command": command,
                "pid": proc.pid,
                "note": f"PID {proc.pid} is alive. Call shell_exec with 'kill {proc.pid}' to terminate if needed.",
            }

        # Process finished — drain tasks will hit EOF on their own
        await asyncio.gather(stdout_task, stderr_task)

        duration = time.time() - start
        return {
            "success": proc.returncode == 0,
            "stdout": _decode(stdout_buf),
            "stderr": _decode(stderr_buf),
            "exit_code": proc.returncode,
            "duration": round(duration, 2),
            "command": command,
            "pid": proc.pid,
        }
