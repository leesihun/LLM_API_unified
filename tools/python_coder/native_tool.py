"""
Native Python Code Executor
Accepts natural language instructions, generates code via LLM, executes via subprocess.

Features:
- Self-debug retry loop: on non-zero exit feeds traceback back to LLM, up to
  PYTHON_EXECUTOR_MAX_RETRIES times.
- Layered timeouts: separate generation / per-execution / idle-stdout / total caps.
- Artifact-exists check: if the instruction mentions output filenames, verifies
  they were actually created before declaring success.
- Retry logging: attempts_used and retries_fired reported in result dict.
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

# Regex for output artifacts mentioned in the instruction.
_ARTIFACT_RE = re.compile(
    r'\b([\w\-]+\.(?:png|jpe?g|gif|svg|pdf|csv|tsv|json|xml|html?|txt|md'
    r'|xlsx?|zip|tar|gz|npy|npz|pkl|pt|pth|onnx|mp4|mp3|wav|parquet))\b',
    re.IGNORECASE,
)


class NativePythonExecutor(BasePythonExecutor):
    """
    Instruction-driven Python executor using subprocess.
    Receives natural language instructions, generates code via LLM, executes it.
    """

    def __init__(self, session_id: str):
        super().__init__(session_id)
        self.workspace = config.PYTHON_WORKSPACE_DIR / session_id
        self.workspace.mkdir(parents=True, exist_ok=True)
        # Layered timeout knobs (fall back to sane values if old config):
        self.generation_timeout = getattr(config, 'PYTHON_GENERATION_TIMEOUT', 120)
        self.execution_timeout = getattr(config, 'PYTHON_EXECUTION_TIMEOUT', 60)
        self.execution_timeout_max = getattr(config, 'PYTHON_EXECUTION_TIMEOUT_MAX', 900)
        self.idle_timeout = getattr(config, 'PYTHON_EXECUTION_IDLE_TIMEOUT', 60)
        self.timeout = getattr(config, 'PYTHON_TOTAL_TIMEOUT', 600)
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

        On non-zero exit, regenerates with the traceback fed back to the LLM
        (bounded by PYTHON_EXECUTOR_MAX_RETRIES and PYTHON_TOTAL_TIMEOUT).
        After a zero-exit, checks that any output files mentioned in the
        instruction actually exist before declaring success.

        Args:
            instruction: Natural language description of the task
            timeout: Per-attempt execution timeout override (clamped to max)
        """
        # Per-attempt execution timeout: caller hint clamped to max, else default.
        if timeout is not None:
            per_exec = min(max(int(timeout), 1), self.execution_timeout_max)
        else:
            per_exec = self.execution_timeout

        total_timeout = self.timeout
        total_deadline = time.time() + total_timeout
        max_retries = getattr(config, 'PYTHON_EXECUTOR_MAX_RETRIES', 2)
        max_attempts = 1 + max_retries

        last_result: Optional[Dict[str, Any]] = None
        prev_code: Optional[str] = None
        prev_stderr: Optional[str] = None
        script_name: Optional[str] = None  # locked on first attempt
        attempts_used = 0
        retries_fired = 0

        for attempt in range(max_attempts):
            if time.time() >= total_deadline:
                break

            attempt_start = time.time()
            attempts_used += 1
            existing_py_files = [f for f in self.list_files() if f.endswith('.py')]

            try:
                code, new_name = await asyncio.wait_for(
                    self._generate_code(
                        instruction, existing_py_files,
                        prev_code=prev_code,
                        prev_stderr=prev_stderr,
                    ),
                    timeout=self.generation_timeout,
                )
            except asyncio.TimeoutError:
                log_to_prompts_file(f"[PYTHON] Generation timeout after {self.generation_timeout}s")
                break

            if script_name is None:
                script_name = new_name  # locked for all retries

            script_path = self.workspace / script_name
            script_path.write_text(code, encoding='utf-8')
            print(f"[PYTHON] Script written: {script_path}")

            if attempt == 0:
                self._log_execution_start(instruction, code, script_name, per_exec, existing_py_files)
            else:
                retries_fired += 1
                print(f"[PYTHON] Retry {attempt}/{max_retries} — feeding back traceback")
                log_to_prompts_file(f"\n[PYTHON] Retry {attempt}/{max_retries}")

            remaining = max(1, int(total_deadline - time.time()))
            result = await self._run_script(
                script_name,
                min(per_exec, remaining),
                attempt_start,
            )
            last_result = result

            # Inject retry counters into result.
            result['attempts_used'] = attempts_used
            result['retries_fired'] = retries_fired

            if result.get('returncode') == 0 and result.get('executed'):
                # Artifact check: verify output files mentioned in instruction exist.
                missing = self._check_artifacts(instruction)
                if missing:
                    artifact_msg = f"Script ran cleanly but expected output file(s) not found: {missing}"
                    log_to_prompts_file(f"[PYTHON] Artifact check failed: {missing}")
                    print(f"[PYTHON] Artifact check failed: {missing}")
                    prev_code = code
                    prev_stderr = artifact_msg
                    result['success'] = False
                    result['returncode'] = -1
                    result['error'] = artifact_msg
                    last_result = result
                    continue  # retry

                return result

            prev_code = code
            prev_stderr = (result.get('stderr') or result.get('error') or '')[:2000]

        if last_result is None:
            last_result = self._result_dict(
                success=False, script_name=script_name or "", executed=False,
                stdout="", stderr="No attempts completed within total timeout",
                returncode=-1, execution_time=0.0,
                error="No attempts completed within total timeout",
                attempts_used=attempts_used, retries_fired=retries_fired,
            )
        else:
            last_result.setdefault('attempts_used', attempts_used)
            last_result.setdefault('retries_fired', retries_fired)

        return last_result

    # ------------------------------------------------------------------
    # Artifact verification
    # ------------------------------------------------------------------

    def _check_artifacts(self, instruction: str) -> List[str]:
        """Return list of output filenames mentioned in instruction that are
        missing or empty in the workspace after execution."""
        mentioned = {m.group(1).lower() for m in _ARTIFACT_RE.finditer(instruction)}
        if not mentioned:
            return []
        missing = []
        for name in mentioned:
            candidate = self.workspace / name
            if not candidate.exists() or candidate.stat().st_size == 0:
                missing.append(name)
        return missing

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

        print(f"\n[PYTHON] Generating code...")
        print(f"[PYTHON] Instruction: {instruction[:200]}{'...' if len(instruction) > 200 else ''}")
        if existing_py_files:
            print(f"[PYTHON] Workspace context: {existing_py_files}")
        if prev_code is not None:
            print(f"[PYTHON] Retry mode: {len(prev_stderr or '')} chars of error context")

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
                idle_timeout=self.idle_timeout,
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
            reason = "idle (no stdout)" if result.idle_killed else f"wall-clock ({exec_timeout}s)"
            error_msg = f"Execution killed: {reason}"
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
        attempts_used: int = 1,
        retries_fired: int = 0,
    ) -> Dict[str, Any]:
        return {
            "success": success,
            "execution_mode": "native",
            "script_path": str((self.workspace / script_name).resolve()) if script_name else None,
            "executed": executed,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": returncode,
            "execution_time": execution_time,
            "files": self._get_workspace_files(),
            "workspace": str(self.workspace),
            "error": error,
            "attempts_used": attempts_used,
            "retries_fired": retries_fired,
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
        try:
            for file_path in self.workspace.iterdir():
                if file_path.is_file():
                    files[file_path.name] = {
                        "size": file_path.stat().st_size,
                        "modified": file_path.stat().st_mtime,
                        "path": str(file_path),
                    }
        except Exception:
            pass
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
        try:
            return [f.name for f in self.workspace.iterdir() if f.is_file()]
        except Exception:
            return []

    def clear_workspace(self) -> None:
        import shutil
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _log_execution_start(self, instruction: str, code: str, script_name: str,
                              timeout: int, existing_files: List[str]) -> None:
        log_to_prompts_file("\n\n" + "=" * 80)
        log_to_prompts_file("TOOL EXECUTION: python_coder (native)")
        log_to_prompts_file("=" * 80)
        log_to_prompts_file(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log_to_prompts_file(f"Session: {self.session_id}")
        log_to_prompts_file(f"Script: {script_name}  Timeout: {timeout}s")
        log_to_prompts_file(f"Workspace files: {existing_files}")
        log_to_prompts_file("")
        log_to_prompts_file("INSTRUCTION:")
        for line in instruction.split('\n')[:20]:
            log_to_prompts_file(f"  {line}")
        log_to_prompts_file("")
        log_to_prompts_file("GENERATED CODE:")
        for line in code.split('\n')[:60]:
            log_to_prompts_file(f"  {line}")

        print(f"\n{'=' * 60}")
        print(f"[PYTHON] Native Executor")
        print(f"Session: {self.session_id}  Script: {script_name}")
        print(f"Instruction: {instruction[:120]}...")

    def _log_execution_result(self, success: bool, returncode: int, execution_time: float,
                               stdout: str, stderr: str, files: Dict) -> None:
        log_to_prompts_file("")
        log_to_prompts_file("-" * 80)
        log_to_prompts_file(f"RESULT: {'SUCCESS' if success else 'FAILED'}  code={returncode}  time={execution_time:.2f}s")
        if stdout:
            log_to_prompts_file("STDOUT:")
            for line in stdout.split('\n')[:50]:
                log_to_prompts_file(f"  {line}")
        if stderr:
            log_to_prompts_file("STDERR:")
            for line in stderr.split('\n')[:20]:
                log_to_prompts_file(f"  {line}")
        if files:
            log_to_prompts_file(f"FILES: {list(files.keys())}")
        log_to_prompts_file("=" * 80)

        print(f"\n[PYTHON] {'OK' if success else 'FAILED'} in {execution_time:.2f}s  rc={returncode}")

    def _log_execution_error(self, error_type: str, error_msg: str, execution_time: float) -> None:
        log_to_prompts_file(f"\nERROR [{error_type}]: {error_msg}  ({execution_time:.2f}s)")
        log_to_prompts_file("=" * 80)
