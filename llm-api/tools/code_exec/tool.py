"""
Direct Python code executor — no second LLM call.

The agent LLM writes the code directly in the tool-call arguments.
This tool writes it to a fresh temp dir, runs it, and the temp dir is
deleted on return. Nothing persists between calls — by design, so
generated test scripts don't pile up on disk.
"""
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

import config
from backend.utils.prompts_log_append import log_to_prompts_file
from backend.utils.subprocess_stream import run_streaming


def _format_timeout(timeout: Optional[int]) -> str:
    return "never" if timeout is None else f"{timeout}s"


class CodeExecTool:
    """Execute Python code supplied directly by the LLM in an ephemeral temp dir."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.max_output_size = getattr(config, "PYTHON_EXECUTOR_MAX_OUTPUT_SIZE", 10 * 1024 * 1024)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        code: str,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Write *code* to a temp dir, run it, then delete the dir."""
        exec_timeout = self._resolve_timeout(timeout)
        start_time = time.time()
        script_name = self._make_script_name(code)

        with tempfile.TemporaryDirectory(prefix="code_exec_") as tmpdir:
            workspace = Path(tmpdir)
            script_path = workspace / script_name
            script_path.write_text(code, encoding="utf-8")

            print(f"\n[CODE_EXEC] Script: {script_path}")
            print(f"[CODE_EXEC] Timeout: {_format_timeout(exec_timeout)}")
            self._log_execution_start(code, script_name, exec_timeout)

            try:
                result = await run_streaming(
                    program=sys.executable,
                    args=[script_name],
                    cwd=str(workspace),
                    timeout=exec_timeout,
                    max_output_size=self.max_output_size,
                )
            except Exception as e:
                execution_time = time.time() - start_time
                msg = str(e)
                print(f"[CODE_EXEC] ERROR: {msg}")
                self._log_execution_error("ERROR", msg, execution_time)
                return self._result_dict(
                    success=False, script_name=script_name, executed=False,
                    stdout="", stderr=msg, returncode=-1,
                    execution_time=execution_time, error=msg,
                )

            execution_time = time.time() - start_time
            if result.timed_out:
                msg = f"Execution timeout after {_format_timeout(exec_timeout)}"
                print(f"[CODE_EXEC] TIMEOUT: {msg}")
                self._log_execution_error("TIMEOUT", msg, execution_time)
                return self._result_dict(
                    success=False, script_name=script_name, executed=False,
                    stdout=result.stdout, stderr=msg, returncode=-1,
                    execution_time=execution_time, error=msg,
                )

            success = result.returncode == 0
            print(f"[CODE_EXEC] returncode={result.returncode}, time={execution_time:.2f}s")
            self._log_execution_result(success, result.returncode, execution_time, result.stdout, result.stderr)
            return self._result_dict(
                success=success, script_name=script_name, executed=True,
                stdout=result.stdout, stderr=result.stderr, returncode=result.returncode,
                execution_time=execution_time,
                error=None if success else result.stderr,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_timeout(timeout: Optional[int]) -> Optional[int]:
        if timeout is None:
            return getattr(config, "PYTHON_EXECUTOR_TIMEOUT", 300)
        timeout = int(timeout)
        if timeout <= 0:
            return None
        return timeout

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

    def _log_execution_start(self, code: str, script_name: str, timeout: Optional[int]) -> None:
        log_to_prompts_file("\n\n" + "=" * 80)
        log_to_prompts_file("TOOL EXECUTION: code_exec")
        log_to_prompts_file("=" * 80)
        log_to_prompts_file(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log_to_prompts_file(f"Session: {self.session_id}")
        log_to_prompts_file(f"Script: {script_name}  Timeout: {_format_timeout(timeout)}")
        log_to_prompts_file("")
        log_to_prompts_file("CODE:")
        log_to_prompts_file("-" * 80)
        log_to_prompts_file(code)
        log_to_prompts_file("-" * 80)

    def _log_execution_result(
        self,
        success: bool,
        returncode: int,
        execution_time: float,
        stdout: str,
        stderr: str,
    ) -> None:
        log_to_prompts_file("")
        log_to_prompts_file(f"RESULT: {'SUCCESS' if success else 'FAILED'}")
        log_to_prompts_file(f"Return Code: {returncode}")
        log_to_prompts_file(f"Execution Time: {execution_time:.2f}s")
        if stdout:
            log_to_prompts_file("STDOUT:")
            log_to_prompts_file(stdout)
        if stderr:
            log_to_prompts_file("STDERR:")
            log_to_prompts_file(stderr)
        log_to_prompts_file("=" * 80)

    def _log_execution_error(self, kind: str, message: str, execution_time: float) -> None:
        log_to_prompts_file("")
        log_to_prompts_file(f"{kind}: {message}")
        log_to_prompts_file(f"Execution Time: {execution_time:.2f}s")
        log_to_prompts_file("=" * 80)

    def _result_dict(
        self,
        success: bool,
        script_name: str,
        executed: bool,
        stdout: str,
        stderr: str,
        returncode: int,
        execution_time: float,
        error: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "success": success,
            "execution_mode": "code_exec",
            "script_name": script_name,
            "executed": executed,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": returncode,
            "execution_time": execution_time,
            "error": error,
        }
