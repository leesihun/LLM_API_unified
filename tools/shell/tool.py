"""
Shell Execution Tool
Run shell commands in a subprocess.
"""
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional

import config

MAX_OUTPUT_SIZE = 50 * 1024  # 50KB cap per stream


class ShellExecTool:
    """Execute shell commands."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.workspace = config.SCRATCH_DIR / session_id
        self.workspace.mkdir(parents=True, exist_ok=True)

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

    def execute(
        self,
        command: str,
        timeout: int = 300,
        working_directory: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a shell command.

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
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
            )

            stdout_chunks: list = []
            stderr_chunks: list = []

            def _drain(pipe, chunks):
                while True:
                    chunk = pipe.read(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)

            t_out = threading.Thread(target=_drain, args=(proc.stdout, stdout_chunks), daemon=True)
            t_err = threading.Thread(target=_drain, args=(proc.stderr, stderr_chunks), daemon=True)
            t_out.start()
            t_err.start()

            try:
                proc.wait(timeout=timeout)
                t_out.join(1)
                t_err.join(1)

                stdout = "".join(stdout_chunks)
                stderr = "".join(stderr_chunks)
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

            except subprocess.TimeoutExpired:
                # Collect whatever arrived so far — do NOT kill the process
                t_out.join(0.5)
                t_err.join(0.5)

                stdout = "".join(stdout_chunks)
                stderr = "".join(stderr_chunks)
                if len(stdout) > MAX_OUTPUT_SIZE:
                    stdout = stdout[:MAX_OUTPUT_SIZE] + "\n...[truncated]"
                if len(stderr) > MAX_OUTPUT_SIZE:
                    stderr = stderr[:MAX_OUTPUT_SIZE] + "\n...[truncated]"

                duration = time.time() - start
                return {
                    "success": False,
                    "still_running": True,
                    "error": f"Process still running after {timeout}s",
                    "stdout": stdout,
                    "stderr": stderr,
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
