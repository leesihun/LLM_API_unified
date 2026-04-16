"""
Direct Python code executor — no second LLM call.

The agent LLM writes the code directly in the tool-call arguments.
This tool just writes it to a file and runs it, skipping the
code-generation LLM round-trip that python_coder requires.
"""
import asyncio
import re
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import config


class CodeExecTool:
    """
    Execute Python code supplied directly by the LLM.

    The workspace is shared with python_coder (same PYTHON_WORKSPACE_DIR /
    session_id directory) so files written by one tool are visible to the other.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.workspace = config.PYTHON_WORKSPACE_DIR / session_id
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.max_output_size = getattr(config, "PYTHON_EXECUTOR_MAX_OUTPUT_SIZE", 10 * 1024 * 1024)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        code: str,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Write *code* to a script file and run it.

        Args:
            code:    Complete Python source to execute.
            timeout: Max seconds (default: config.PYTHON_EXECUTOR_TIMEOUT).
        """
        exec_timeout = timeout or getattr(config, "PYTHON_EXECUTOR_TIMEOUT", 300)
        start_time = time.time()

        script_name = self._make_script_name(code)
        script_path = self.workspace / script_name
        script_path.write_text(code, encoding="utf-8")

        print(f"\n[CODE_EXEC] Script: {script_path}")
        print(f"[CODE_EXEC] Timeout: {exec_timeout}s")

        return await asyncio.to_thread(
            self._run_script, script_name, exec_timeout, start_time
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_script_name(self, code: str) -> str:
        """Generate a human-readable timestamped script filename."""
        func_matches = re.findall(r"^\s*def\s+(\w+)", code, re.MULTILINE)
        class_matches = re.findall(r"^\s*class\s+(\w+)", code, re.MULTILINE)
        ts = datetime.now().strftime("%H%M%S")
        if func_matches:
            return f"{func_matches[0]}_{ts}.py"
        if class_matches:
            return f"{class_matches[0].lower()}_{ts}.py"
        return f"exec_{ts}.py"

    def _run_script(self, script_name: str, exec_timeout: int, start_time: float) -> Dict[str, Any]:
        """Synchronous subprocess execution (called via asyncio.to_thread)."""
        try:
            result = subprocess.run(
                [sys.executable, script_name],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=exec_timeout,
            )

            stdout = result.stdout
            stderr = result.stderr
            if len(stdout) > self.max_output_size:
                stdout = stdout[: self.max_output_size] + "\n... (output truncated)"
            if len(stderr) > self.max_output_size:
                stderr = stderr[: self.max_output_size] + "\n... (output truncated)"

            execution_time = time.time() - start_time
            success = result.returncode == 0

            print(f"[CODE_EXEC] returncode={result.returncode}, time={execution_time:.2f}s")

            return {
                "success": success,
                "execution_mode": "code_exec",
                "script_path": str((self.workspace / script_name).resolve()),
                "executed": True,
                "stdout": stdout,
                "stderr": stderr,
                "returncode": result.returncode,
                "execution_time": execution_time,
                "files": self._list_workspace_files(),
                "workspace": str(self.workspace),
                "error": None if success else stderr,
            }

        except subprocess.TimeoutExpired:
            execution_time = time.time() - start_time
            msg = f"Execution timeout after {exec_timeout}s"
            print(f"[CODE_EXEC] TIMEOUT: {msg}")
            return {
                "success": False,
                "execution_mode": "code_exec",
                "script_path": str((self.workspace / script_name).resolve()),
                "executed": False,
                "stdout": "",
                "stderr": msg,
                "returncode": -1,
                "execution_time": execution_time,
                "files": self._list_workspace_files(),
                "workspace": str(self.workspace),
                "error": msg,
            }

        except Exception as e:
            execution_time = time.time() - start_time
            msg = str(e)
            print(f"[CODE_EXEC] ERROR: {msg}")
            return {
                "success": False,
                "execution_mode": "code_exec",
                "script_path": str((self.workspace / script_name).resolve()),
                "executed": False,
                "stdout": "",
                "stderr": msg,
                "returncode": -1,
                "execution_time": execution_time,
                "files": self._list_workspace_files(),
                "workspace": str(self.workspace),
                "error": msg,
            }

    def _list_workspace_files(self) -> List[str]:
        try:
            return [f.name for f in self.workspace.iterdir() if f.is_file()]
        except Exception:
            return []
