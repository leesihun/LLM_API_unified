"""
Python Code Executor Tool
Accepts natural language instructions, generates Python code via LLM, then executes it.
"""
import sys
import time
import subprocess
import re
import httpx
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime

import config


def log_to_prompts_file(message: str):
    """Write message to prompts.log"""
    try:
        with open(config.PROMPTS_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(message + '\n')
    except Exception as e:
        print(f"[WARNING] Failed to write to prompts.log: {e}")


class PythonCoderTool:
    """
    Instruction-driven Python executor.
    Receives natural language instructions, generates code via LLM, executes it.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.workspace = config.PYTHON_WORKSPACE_DIR / session_id
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.timeout = config.PYTHON_EXECUTOR_TIMEOUT
        self.max_output_size = config.PYTHON_EXECUTOR_MAX_OUTPUT_SIZE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        instruction: str,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Generate and execute Python code from a natural language instruction.

        Args:
            instruction: Natural language description of the task
            timeout: Execution timeout in seconds (optional)
        """
        exec_timeout = timeout or self.timeout
        start_time = time.time()

        existing_py_files = [f for f in self.list_files() if f.endswith('.py')]
        code, script_name = self._generate_code(instruction, existing_py_files)

        script_path = self.workspace / script_name

        self._log_execution_start(instruction, code, script_name, exec_timeout, existing_py_files)

        script_path.write_text(code, encoding='utf-8')
        print(f"[PYTHON] Script written: {script_path}")

        return self._run_script(script_name, exec_timeout, start_time)

    # ------------------------------------------------------------------
    # Code generation from instruction
    # ------------------------------------------------------------------

    def _generate_code(self, instruction: str, existing_py_files: List[str]) -> Tuple[str, str]:
        """Generate Python code from natural language instruction via LLM."""
        files_context = self._build_workspace_context(existing_py_files)

        if files_context:
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

        code = self._llm_call_sync(prompt)
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
    # Synchronous LLM call (safe inside async event loop)
    # ------------------------------------------------------------------

    def _llm_call_sync(self, prompt: str) -> str:
        """Call llama.cpp synchronously to generate code."""
        url = f"{config.LLAMACPP_HOST.rstrip('/')}/v1/chat/completions"
        temperature = config.TOOL_PARAMETERS.get(
            'python_coder', {}
        ).get('temperature', config.DEFAULT_TEMPERATURE)

        print(f"[PYTHON] LLM call: model={config.LLAMACPP_MODEL}, temperature={temperature}")

        payload = {
            "model": config.LLAMACPP_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }

        resp = httpx.post(url, json=payload, timeout=config.PYTHON_CODER_TIMEOUT)
        resp.raise_for_status()

        content = resp.json()["choices"][0]["message"]["content"]
        return self._extract_python_code(content)

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
    # Script execution
    # ------------------------------------------------------------------

    def _run_script(self, script_name: str, exec_timeout: int, start_time: float) -> Dict[str, Any]:
        """Execute a Python script and return structured results."""
        print(f"\n[PYTHON] Executing {script_name}...")
        print(f"  Python: {sys.executable}")
        print(f"  Working dir: {self.workspace}")

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
                stdout = stdout[:self.max_output_size] + "\n... (output truncated)"
            if len(stderr) > self.max_output_size:
                stderr = stderr[:self.max_output_size] + "\n... (output truncated)"

            execution_time = time.time() - start_time
            files = self._get_workspace_files()
            success = result.returncode == 0

            self._log_execution_result(success, result.returncode, execution_time, stdout, stderr, files)

            return {
                "success": success,
                "stdout": stdout,
                "stderr": stderr,
                "returncode": result.returncode,
                "execution_time": execution_time,
                "files": files,
                "workspace": str(self.workspace),
                "error": None if success else stderr,
            }

        except subprocess.TimeoutExpired:
            execution_time = time.time() - start_time
            error_msg = f"Execution timeout after {exec_timeout} seconds"
            print(f"[PYTHON] ERROR: {error_msg}")
            self._log_execution_error("TIMEOUT", error_msg, execution_time)
            return {
                "success": False, "stdout": "", "stderr": error_msg,
                "returncode": -1, "execution_time": execution_time,
                "files": self._get_workspace_files(),
                "workspace": str(self.workspace), "error": error_msg,
            }

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = str(e)
            print(f"[PYTHON] ERROR: {error_msg}")
            self._log_execution_error("ERROR", error_msg, execution_time)
            return {
                "success": False, "stdout": "", "stderr": error_msg,
                "returncode": -1, "execution_time": execution_time,
                "files": self._get_workspace_files(),
                "workspace": str(self.workspace), "error": error_msg,
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
        log_to_prompts_file("TOOL EXECUTION: python_coder")
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
