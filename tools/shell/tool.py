"""
Shell Execution Tool
Run shell commands via async subprocess (non-blocking).
"""
import asyncio
import time
from pathlib import Path
from typing import Dict, Any, Optional

import config

MAX_OUTPUT_SIZE = 50 * 1024  # 50KB cap per stream

# Track already-created workspace directories to skip redundant mkdir calls
_created_dirs: set = set()


class ShellExecTool:
    """Execute shell commands via async subprocess."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.workspace = config.SCRATCH_DIR / session_id
        if session_id not in _created_dirs:
            self.workspace.mkdir(parents=True, exist_ok=True)
            _created_dirs.add(session_id)

    def _resolve_working_directory(self, working_directory: Optional[str]) -> Path:
        """
        Resolve working directory for command execution.

        Absolute paths are used directly.
        Relative paths are resolved from current working directory.
        If unset, default to session workspace for compatibility.
        """
        if not working_directory:
            return self.workspace.resolve()

        cwd = Path(working_directory).expanduser()
        if cwd.is_absolute():
            return cwd.resolve()
        return (Path.cwd() / cwd).resolve()

    async def execute(
        self,
        command: str,
        timeout: int = 300,
        working_directory: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a shell command asynchronously.

        On timeout, does NOT kill the process — returns partial output so far
        plus the PID, allowing the caller to decide whether to kill or wait.

        Args:
            command: The shell command to run
            timeout: Seconds to wait before returning partial output (process keeps running)
            working_directory: Absolute path or path relative to current working directory
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

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )

                stdout = stdout_bytes.decode('utf-8', errors='replace')
                stderr = stderr_bytes.decode('utf-8', errors='replace')
                if len(stdout) > MAX_OUTPUT_SIZE:
                    stdout = stdout[:MAX_OUTPUT_SIZE] + "\n...[truncated]"
                if len(stderr) > MAX_OUTPUT_SIZE:
                    stderr = stderr[:MAX_OUTPUT_SIZE] + "\n...[truncated]"

                duration = time.time() - start
                return {
                    "success": proc.returncode == 0,
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": proc.returncode,
                    "duration": round(duration, 2),
                    "command": command,
                    "pid": proc.pid,
                }

            except asyncio.TimeoutError:
                # Process is still running — collect whatever we can
                duration = time.time() - start
                return {
                    "success": False,
                    "still_running": True,
                    "error": f"Process still running after {timeout}s",
                    "stdout": "",
                    "stderr": "",
                    "duration": round(duration, 2),
                    "command": command,
                    "pid": proc.pid,
                    "note": f"PID {proc.pid} is alive. Call shell_exec with 'kill {proc.pid}' to terminate if needed.",
                }

        except Exception as e:
            duration = time.time() - start
            return {
                "success": False,
                "error": str(e),
                "duration": round(duration, 2),
                "command": command,
            }
