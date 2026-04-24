"""
Native Python Code Executor
Accepts natural language instructions, generates code via LLM, executes via subprocess.
"""
import sys
import time
import re
import asyncio
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime

import config
from backend.core.llm_backend import llm_backend
from backend.utils.prompts_log_append import log_to_prompts_file
from backend.utils.subprocess_stream import run_streaming
from tools.python_coder.base import BasePythonExecutor


class NativePythonExecutor(BasePythonExecutor):
    """
    Instruction-driven Python executor using subprocess.
    Receives natural language instructions, generates code via LLM, executes it.
    """

    def __init__(self, session_id: str):
        super().__init__(session_id)
        self.workspace = config.PYTHON_WORKSPACE_DIR / session_id
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.timeout = config.PYTHON_EXECUTOR_TIMEOUT
        self.max_output_size = config.PYTHON_EXECUTOR_MAX_OUTPUT_SIZE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        instruction: str,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Generate and execute Python code from a natural language instruction.

        On non-zero exit, regenerate with the traceback fed back to the LLM
        (bounded by PYTHON_EXECUTOR_MAX_RETRIES and PYTHON_EXECUTOR_TOTAL_TIMEOUT).

        Args:
            instruction: Natural language description of the task
            timeout: Per-attempt subprocess execution timeout (optional)
        """
        exec_timeout = timeout or self.timeout
        total_timeout = getattr(config, 'PYTHON_EXECUTOR_TOTAL_TIMEOUT', 180)
        max_retries = getattr(config, 'PYTHON_EXECUTOR_MAX_RETRIES', 2)
        total_deadline = time.time() + total_timeout
        max_attempts = 1 + max_retries

        last_result: Optional[Dict[str, Any]] = None
        prev_code: Optional[str] = None
        prev_stderr: Optional[str] = None

        for attempt in range(max_attempts):
            if time.time() >= total_deadline:
                break

            attempt_start = time.time()
            existing_py_files = [f for f in self.list_files() if f.endswith('.py')]

            code, script_name = await self._generate_code(
                instruction,
                existing_py_files,
                prev_code=prev_code,
                prev_stderr=prev_stderr,
            )
            script_path = self.workspace / script_name

            if attempt == 0:
                self._log_execution_start(instruction, code, script_name, exec_timeout, existing_py_files)
            else:
                print(f"[PYTHON] Retry {attempt}/{max_retries} after previous failure")
                log_to_prompts_file(f"\n[PYTHON] Retry attempt {attempt}/{max_retries}")
                log_to_prompts_file(f"  Script: {script_name}")

            script_path.write_text(code, encoding='utf-8')
            print(f"[PYTHON] Script written: {script_path}")

            remaining = max(1, int(total_deadline - time.time()))
            per_attempt_timeout = min(exec_timeout, remaining)
            result = await self._run_script(script_name, per_attempt_timeout, attempt_start)
            last_result = result

            if result.get('returncode') == 0 and result.get('executed'):
                return result

            prev_code = code
            prev_stderr = (result.get('stderr') or result.get('error') or '')[:2000]

        return last_result if last_result is not None else self._result_dict(
            success=False, script_name="", executed=False,
            stdout="", stderr="No attempts completed within total timeout",
            returncode=-1, execution_time=0.0,
            error="No attempts completed within total timeout",
        )

    # ------------------------------------------------------------------
    # Code generation from instruction
    # ------------------------------------------------------------------

    async def _generate_code(
        self,
        instruction: str,
        existing_py_files: List[str],
        prev_code: Optional[str] = None,
        prev_stderr: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Generate Python code from natural language instruction via LLM.

        When prev_code and prev_stderr are provided, the prompt asks the LLM
        to fix the previous attempt using the traceback.
        """
        files_context = self._build_workspace_context(existing_py_files)

        if prev_code is not None and prev_stderr:
            prompt = (
                "The previous Python script failed. Fix the error below.\n\n"
                "**Previous code:**\n"
                f"```python\n{prev_code}\n```\n\n"
                "**Error / traceback:**\n"
                f"```\n{prev_stderr}\n```\n\n"
                f"**Original instruction:** {instruction}\n\n"
                "Output ONLY the corrected complete Python code:\n```python"
            )
        elif files_context:
            prompt = (
                "Generate executable Python code based on the instruction below.\n\n"
                f"**Existing workspace files:**{files_context}\n\n"
                f"**Instruction:** {instruction}\n\n"
                "**Rules:**\n"
                "- If the instruction relates to existing code, edit/merge with the existing file\n"
                "- Maintain variable and import continuity with existing files\n"
                "- Remove duplicate imports\n\n"
                "Output ONLY the complete Python code:\n```python"
            )
        else:
            prompt = (
                "Generate executable Python code based on the instruction below.\n\n"
                f"**Instruction:** {instruction}\n\n"
                "Output ONLY the complete Python code:\n```python"
            )

        print(f"\n[PYTHON] Generating code from instruction...")
        print(f"[PYTHON] Instruction: {instruction[:200]}{'...' if len(instruction) > 200 else ''}")
        if existing_py_files:
            print(f"[PYTHON] Workspace context: {existing_py_files}")
        if prev_code is not None:
            print(f"[PYTHON] Retry mode: feeding back {len(prev_stderr or '')} chars of stderr")

        code = await self._llm_call_async(prompt)
        script_name = self._generate_script_name(code)

        print(f"[PYTHON] Generated {len(code)} chars → {script_name}")
        return code, script_name

    def _build_workspace_context(self, existing_py_files: List[str]) -> str:
        if not existing_py_files:
            return ""
        parts = []
        for f in existing_py_files:
            content = self.read_file(f)
            if content:
                parts.append(f"\n### {f}\n```python\n{content}\n```")
        return "".join(parts)

    # ------------------------------------------------------------------
    # Async LLM call — streams through the shared llm_backend for free
    # connection pooling, interceptor logging, and KV cache reuse.
    # ------------------------------------------------------------------

    async def _llm_call_async(self, prompt: str) -> str:
        temperature = config.TOOL_PARAMETERS.get(
            'python_coder', {}
        ).get('temperature', config.DEFAULT_TEMPERATURE)

        print(f"[PYTHON] LLM call: model={config.LLAMACPP_MODEL}, temperature={temperature}")

        response = await llm_backend.chat(
            messages=[{"role": "user", "content": prompt}],
            model=config.LLAMACPP_MODEL,
            temperature=temperature,
            session_id=self.session_id,
            agent_type="tool:python_coder",
        )
        return self._extract_python_code(response.content or "")

    def _extract_python_code(self, response: str) -> str:
        """Extract Python code from LLM response markdown."""
        if "```python" in response:
            parts = response.split("```python")
            if len(parts) > 1:
                return parts[1].split("```")[0].strip()
        if "```" in response:
            parts = response.split("```")
            if len(parts) >= 3:
                return parts[1].strip()
        return response.strip()

    # ------------------------------------------------------------------
    # Script execution (streams subprocess output incrementally)
    # ------------------------------------------------------------------

    async def _run_script(self, script_name: str, exec_timeout: int, start_time: float) -> Dict[str, Any]:
        """Execute a Python script with streaming output capture."""
        print(f"\n[PYTHON] Executing {script_name}...")
        print(f"  Python: {sys.executable}")
        print(f"  Working dir: {self.workspace}")

        try:
            result = await run_streaming(
                program=sys.executable,
                args=[script_name],
                cwd=str(self.workspace),
                timeout=exec_timeout,
                max_output_size=self.max_output_size,
            )
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = str(e)
            print(f"[PYTHON] ERROR: {error_msg}")
            self._log_execution_error("ERROR", error_msg, execution_time)
            return self._result_dict(
                success=False, script_name=script_name, executed=False,
                stdout="", stderr=error_msg, returncode=-1,
                execution_time=execution_time, error=error_msg,
            )

        execution_time = time.time() - start_time
        files = self._get_workspace_files()

        if result.timed_out:
            error_msg = f"Execution timeout after {exec_timeout} seconds"
            print(f"[PYTHON] ERROR: {error_msg}")
            self._log_execution_error("TIMEOUT", error_msg, execution_time)
            return self._result_dict(
                success=False, script_name=script_name, executed=False,
                stdout=result.stdout, stderr=error_msg, returncode=-1,
                execution_time=execution_time, error=error_msg,
            )

        success = result.returncode == 0
        self._log_execution_result(success, result.returncode, execution_time, result.stdout, result.stderr, files)
        return self._result_dict(
            success=success, script_name=script_name, executed=True,
            stdout=result.stdout, stderr=result.stderr, returncode=result.returncode,
            execution_time=execution_time,
            error=None if success else result.stderr,
        )

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
            "execution_mode": "native",
            "script_path": str((self.workspace / script_name).resolve()),
            "executed": executed,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": returncode,
            "execution_time": execution_time,
            "files": self._get_workspace_files(),
            "workspace": str(self.workspace),
            "error": error,
        }

    # ------------------------------------------------------------------
    # Script naming
    # ------------------------------------------------------------------

    def _generate_script_name(self, code: str) -> str:
        """Generate human-readable script name from generated code."""
        func_matches = re.findall(r'^\s*def\s+(\w+)', code, re.MULTILINE)
        class_matches = re.findall(r'^\s*class\s+(\w+)', code, re.MULTILINE)

        if func_matches:
            name = func_matches[0]
        elif class_matches:
            name = class_matches[0]
        else:
            import_matches = re.findall(r'^\s*import\s+(\w+)', code, re.MULTILINE)
            from_matches = re.findall(r'^\s*from\s+(\w+)', code, re.MULTILINE)
            imports = import_matches + from_matches
            if imports:
                name = imports[0] + "_script"
            else:
                return f"script_{int(time.time() * 1000)}.py"

        name = re.sub(r'[^a-zA-Z0-9_]', '_', name[:50])
        return f"{name}.py"

    # ------------------------------------------------------------------
    # Workspace helpers
    # ------------------------------------------------------------------

    def _get_workspace_files(self) -> Dict[str, Any]:
        files = {}
        for file_path in self.workspace.iterdir():
            if file_path.is_file():
                files[file_path.name] = {
                    "size": file_path.stat().st_size,
                    "modified": file_path.stat().st_mtime,
                    "path": str(file_path),
                }
        return files

    def read_file(self, filename: str) -> Optional[str]:
        file_path = self.workspace / filename
        if not file_path.exists():
            return None
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return None

    def list_files(self) -> List[str]:
        return [f.name for f in self.workspace.iterdir() if f.is_file()]

    def clear_workspace(self):
        import shutil
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log_execution_start(
        self, instruction: str, code: str, script_name: str,
        exec_timeout: int, existing_py_files: List[str],
    ):
        log_to_prompts_file("\n\n")
        log_to_prompts_file("=" * 80)
        log_to_prompts_file("TOOL EXECUTION: python_coder (native)")
        log_to_prompts_file("=" * 80)
        log_to_prompts_file(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log_to_prompts_file(f"Session ID: {self.session_id}")
        log_to_prompts_file(f"Workspace: {self.workspace}")
        log_to_prompts_file(f"Script: {script_name}")
        log_to_prompts_file(f"Instruction: {instruction}")
        log_to_prompts_file(f"Generated Code Length: {len(code)} chars")
        log_to_prompts_file(f"Timeout: {exec_timeout}s")
        if existing_py_files:
            log_to_prompts_file(f"Workspace Context: {existing_py_files}")
        log_to_prompts_file("")
        log_to_prompts_file("GENERATED CODE:")
        for line in code.split('\n'):
            log_to_prompts_file(f"  {line}")

        print("\n" + "=" * 80)
        print("[PYTHON TOOL] execute()")
        print("=" * 80)
        print(f"Session ID: {self.session_id}")
        print(f"Workspace: {self.workspace}")
        print(f"Script: {script_name}")
        print(f"Generated code: {len(code)} chars")
        print(f"Timeout: {exec_timeout}s")
        if existing_py_files:
            print(f"Workspace context: {existing_py_files}")

    def _log_execution_result(
        self, success: bool, returncode: int, execution_time: float,
        stdout: str, stderr: str, files: Dict[str, Any],
    ):
        print(f"\n[PYTHON] Completed in {execution_time:.2f}s  return_code={returncode}")
        if stdout:
            preview = stdout[:300] + "..." if len(stdout) > 300 else stdout
            print(f"[PYTHON] STDOUT:\n{preview}")
        if stderr:
            preview = stderr[:300] + "..." if len(stderr) > 300 else stderr
            print(f"[PYTHON] STDERR:\n{preview}")
        if files:
            print(f"[PYTHON] Files: {list(files.keys())}")

        log_to_prompts_file("")
        log_to_prompts_file("OUTPUT:")
        log_to_prompts_file(f"  Status: {'SUCCESS' if success else 'FAILED'}")
        log_to_prompts_file(f"  Return Code: {returncode}")
        log_to_prompts_file(f"  Execution Time: {execution_time:.2f}s")
        if stdout:
            log_to_prompts_file("")
            log_to_prompts_file("STDOUT:")
            for line in stdout.split('\n'):
                log_to_prompts_file(f"  {line}")
        if stderr:
            log_to_prompts_file("")
            log_to_prompts_file("STDERR:")
            for line in stderr.split('\n'):
                log_to_prompts_file(f"  {line}")
        if files:
            log_to_prompts_file("")
            log_to_prompts_file("FILES:")
            for filename, meta in files.items():
                log_to_prompts_file(f"  {filename} ({meta['size']} bytes)")
        log_to_prompts_file("")
        log_to_prompts_file("=" * 80)

    def _log_execution_error(self, status: str, error_msg: str, execution_time: float):
        log_to_prompts_file("")
        log_to_prompts_file("OUTPUT:")
        log_to_prompts_file(f"  Status: {status}")
        log_to_prompts_file(f"  Error: {error_msg}")
        log_to_prompts_file(f"  Execution Time: {execution_time:.2f}s")
        log_to_prompts_file("")
        log_to_prompts_file("=" * 80)
