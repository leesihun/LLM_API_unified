"""
Shell Execution Tool
Run shell commands in a sandboxed subprocess within the scratch workspace.
"""
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional

import config

MAX_OUTPUT_SIZE = 50 * 1024  # 50KB cap per stream


class ShellExecTool:
    """Execute shell commands sandboxed to the session scratch workspace."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.workspace = config.SCRATCH_DIR / session_id
        self.workspace.mkdir(parents=True, exist_ok=True)

    def execute(
        self,
        command: str,
        timeout: int = 30,
        working_directory: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a shell command.

        Args:
            command: The shell command to run
            timeout: Maximum execution time in seconds
            working_directory: Working directory relative to scratch (optional)
        """
        if working_directory:
            cwd = (self.workspace / working_directory).resolve()
            if not str(cwd).startswith(str(self.workspace.resolve())):
                raise PermissionError("Access denied: working_directory escapes workspace")
            cwd.mkdir(parents=True, exist_ok=True)
        else:
            cwd = self.workspace

        start = time.time()
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding='utf-8',
                errors='replace',
            )
            duration = time.time() - start

            stdout = result.stdout
            stderr = result.stderr
            if len(stdout) > MAX_OUTPUT_SIZE:
                stdout = stdout[:MAX_OUTPUT_SIZE] + "\n...[truncated]"
            if len(stderr) > MAX_OUTPUT_SIZE:
                stderr = stderr[:MAX_OUTPUT_SIZE] + "\n...[truncated]"

            return {
                "success": result.returncode == 0,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": result.returncode,
                "duration": round(duration, 2),
                "command": command,
            }

        except subprocess.TimeoutExpired:
            duration = time.time() - start
            return {
                "success": False,
                "error": f"Command timed out after {timeout}s",
                "duration": round(duration, 2),
                "command": command,
            }
        except Exception as e:
            duration = time.time() - start
            return {
                "success": False,
                "error": str(e),
                "duration": round(duration, 2),
                "command": command,
            }
