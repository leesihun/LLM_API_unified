"""
OpenCode Python Code Executor
Two-stage execution: OpenCode generates code, then Python executor runs it
"""
import asyncio
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

import config
from backend.utils.prompts_log_append import log_to_prompts_file
from backend.utils.subprocess_stream import run_streaming
from tools.python_coder.base import BasePythonExecutor

# Pre-compiled regexes — used on every line of streaming output and parse calls
_ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*[mGKHF]|\x1b\][^\x07]*\x07|\x1b[=><]')
_CONTROL_CHAR_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

# Pre-compiled filename extraction patterns (used every execution in _find_python_file_to_run)
_FILENAME_PATTERNS = [
    re.compile(r'saved (?:to |as )?["\']?(\w+\.py)["\']?', re.IGNORECASE),
    re.compile(r'created ["\']?(\w+\.py)["\']?', re.IGNORECASE),
    re.compile(r'wrote ["\']?(\w+\.py)["\']?', re.IGNORECASE),
    re.compile(r'file[:\s]+["\']?(\w+\.py)["\']?', re.IGNORECASE),
    re.compile(r'(\w+\.py)', re.IGNORECASE),  # Last resort: any .py filename
]


class OpenCodeExecutor(BasePythonExecutor):
    """
    OpenCode-based executor with two-stage execution:

    Stage 1: OpenCode generates Python code and saves to file
    Stage 2: Python subprocess runs the generated code

    This separation ensures clean code generation and reliable execution.
    """

    _http_client: Optional[httpx.AsyncClient] = None
    # Class-level port-alive cache (avoids socket check on every call)
    _port_alive_until: float = 0

    def __init__(self, session_id: str):
        """
        Initialize OpenCode executor

        Args:
            session_id: LLM API session ID for workspace isolation
        """
        super().__init__(session_id)

        self.workspace = config.PYTHON_WORKSPACE_DIR / session_id
        self.workspace.mkdir(parents=True, exist_ok=True)

        self.timeout = config.OPENCODE_TIMEOUT
        self.python_timeout = getattr(config, 'PYTHON_EXECUTOR_TIMEOUT', 60)
        self.max_output_size = config.PYTHON_EXECUTOR_MAX_OUTPUT_SIZE

    @staticmethod
    def _opencode_log_mode() -> str:
        return str(getattr(config, "OPENCODE_LOG_VERBOSITY", "summary")).lower()

    @classmethod
    def _debug_log_enabled(cls) -> bool:
        return cls._opencode_log_mode() == "debug"

    @classmethod
    def _summary_log_enabled(cls) -> bool:
        return cls._opencode_log_mode() in {"summary", "debug"}

    @classmethod
    def _get_http_client(cls) -> httpx.AsyncClient:
        if cls._http_client is None:
            cls._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return cls._http_client

    def _build_execution_result(
        self,
        success: bool,
        script_path: Optional[str],
        executed: bool,
        stdout: str,
        stderr: str,
        returncode: int,
        execution_time: float,
        files: Dict[str, Any],
        error: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "success": bool(success and executed and returncode == 0),
            "execution_mode": "opencode",
            "script_path": script_path,
            "executed": executed,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": returncode,
            "execution_time": execution_time,
            "files": files,
            "workspace": str(self.workspace),
            "error": error,
        }

    def _select_candidate_script(
        self,
        before_files: set[Path],
        after_files: set[Path],
        opencode_output: str,
    ) -> Optional[Path]:
        new_or_updated: set[Path] = set(after_files - before_files)
        cutoff = time.time() - 120
        for path in (after_files & before_files):
            try:
                if path.stat().st_mtime > cutoff:
                    new_or_updated.add(path)
            except OSError:
                continue
        return self._find_python_file_to_run(new_or_updated, opencode_output, all_py_files=after_files)

    def _is_runnable_python_file(self, script_path: Path) -> Tuple[bool, str]:
        if not script_path.exists():
            return False, f"Missing generated script: {script_path}"
        try:
            content = script_path.read_text(encoding="utf-8").strip()
        except Exception as exc:
            return False, f"Failed to read generated script: {exc}"
        if not content:
            return False, "Generated script is empty"
        if "```" in content:
            return False, "Generated script contains markdown fences and is not directly runnable"
        return True, ""

    async def _attempt_recovery_execution(
        self,
        workspace_py_after: set[Path],
        opencode_output: str,
        timeout: int,
        reason: str,
    ) -> Dict[str, Any]:
        self._log_stage(f"RECOVERY EXECUTION: {reason}")
        script_path = self._find_python_file_to_run(workspace_py_after, opencode_output, all_py_files=workspace_py_after)
        if script_path is None:
            return {
                "executed": False,
                "script_path": None,
                "stdout": "",
                "stderr": "",
                "returncode": -1,
                "error": f"{reason}. Recovery failed: no python file available in workspace.",
            }

        try:
            result = await run_streaming(
                program=sys.executable,
                args=[script_path.name],
                cwd=str(self.workspace),
                timeout=min(timeout, self.python_timeout),
                max_output_size=self.max_output_size,
            )
        except Exception as exc:
            return {
                "executed": False,
                "script_path": str(script_path.resolve()),
                "stdout": "",
                "stderr": str(exc),
                "returncode": -1,
                "error": f"{reason}. Recovery execution failed: {exc}",
            }

        if result.timed_out:
            return {
                "executed": False,
                "script_path": str(script_path.resolve()),
                "stdout": result.stdout,
                "stderr": f"Recovery execution timeout after {timeout}s",
                "returncode": -1,
                "error": f"{reason}. Recovery execution timeout.",
            }

        return {
            "executed": True,
            "script_path": str(script_path.resolve()),
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "error": None if result.returncode == 0 else (result.stderr or reason),
        }

    async def _recover_and_finish(
        self,
        workspace_py_after: set,
        opencode_output: str,
        exec_timeout: int,
        start_time: float,
        reason: str,
    ) -> Dict[str, Any]:
        """Attempt recovery execution, build final result, log, and return."""
        recovery = await self._attempt_recovery_execution(
            workspace_py_after=workspace_py_after,
            opencode_output=opencode_output,
            timeout=exec_timeout,
            reason=reason,
        )
        execution_time = time.time() - start_time
        files = self._get_workspace_files()
        result = self._build_execution_result(
            success=recovery["returncode"] == 0,
            script_path=recovery.get("script_path"),
            executed=recovery.get("executed", False),
            stdout=recovery.get("stdout", ""),
            stderr=recovery.get("stderr", ""),
            returncode=recovery.get("returncode", -1),
            execution_time=execution_time,
            files=files,
            error=recovery.get("error"),
        )
        self._log_result(
            result["success"], result["returncode"], result["execution_time"],
            result["stdout"], result["stderr"], result["files"], result["error"],
        )
        return result

    async def execute(
        self,
        instruction: str,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute natural language instruction using two-stage approach:
        1. OpenCode generates Python code
        2. Python subprocess runs the generated code

        Args:
            instruction: Natural language description of the task
            timeout: Execution timeout in seconds

        Returns:
            Standardized execution result dictionary with combined outputs
        """
        exec_timeout = timeout or self.timeout
        start_time = time.time()

        workspace_abs = str(self.workspace.resolve())
        prefix = (
            "Write one complete runnable Python script for the task.\n\n"
            f"WORKING DIRECTORY: {workspace_abs}\n"
            "RULES:\n"
            f"- Save exactly one .py file under {workspace_abs}\n"
            "- Use informative print statements for major steps\n"
            "- Use absolute paths when accessing files outside the working directory\n"
            "- Do not return markdown or explanations, only perform the coding work\n\n"
            "TASK: "
        )

        instruction = prefix + instruction

        # Log execution start
        self._log_start(instruction, exec_timeout)

        # Track files before OpenCode runs
        workspace_py_before = set(self._get_python_files())
        # Only snapshot project root when HTTP server mode is possible (stray files only happen there)
        http_possible = await self._is_server_available()
        project_root = Path(config.__file__).resolve().parent
        root_py_before = set(project_root.glob("*.py")) if http_possible else set()

        # Stage 1: OpenCode generates/updates a script
        print(f"\n[OPENCODE] Code generation stage...")
        self._log_stage("CODE GENERATION (OpenCode)")

        opencode_result = await self._run_opencode(instruction, exec_timeout)

        # Relocate .py files that landed in the project root (HTTP server mode only)
        if http_possible:
            self._relocate_stray_files(root_py_before, project_root)

        workspace_py_after = set(self._get_python_files())
        opencode_output = opencode_result.get("output", "")

        if not opencode_result["success"]:
            return await self._recover_and_finish(
                workspace_py_after, opencode_output, exec_timeout, start_time,
                f"OpenCode failed: {opencode_result.get('error', 'unknown error')}",
            )

        # Stage 2: deterministically choose and execute script
        candidate_script = self._select_candidate_script(
            before_files=workspace_py_before,
            after_files=workspace_py_after,
            opencode_output=opencode_output,
        )

        if candidate_script is None:
            return await self._recover_and_finish(
                workspace_py_after, opencode_output, exec_timeout, start_time,
                "OpenCode did not generate a runnable Python script",
            )

        runnable, reason = self._is_runnable_python_file(candidate_script)
        if not runnable:
            return await self._recover_and_finish(
                workspace_py_after, opencode_output, exec_timeout, start_time,
                reason,
            )

        python_result = await self._run_python_file(candidate_script, min(exec_timeout, self.python_timeout))
        combined_stdout = self._combine_outputs(
            opencode_output=opencode_output,
            python_file=candidate_script,
            python_stdout=python_result["stdout"],
            python_stderr=python_result["stderr"],
            python_returncode=python_result["returncode"],
        )

        execution_time = time.time() - start_time
        result = self._build_execution_result(
            success=python_result["returncode"] == 0,
            script_path=str(candidate_script.resolve()),
            executed=True,
            stdout=combined_stdout,
            stderr=python_result["stderr"],
            returncode=python_result["returncode"],
            execution_time=execution_time,
            files=self._get_workspace_files(),
            error=None if python_result["returncode"] == 0 else python_result["stderr"],
        )
        self._log_result(
            result["success"],
            result["returncode"],
            result["execution_time"],
            result["stdout"],
            result["stderr"],
            result["files"],
            result["error"],
        )
        return result

    def _is_server_available_sync(self) -> bool:
        """Check if OpenCode server is up (sync), with 30s TTL cache."""
        if time.time() < OpenCodeExecutor._port_alive_until:
            return True
        from tools.python_coder.opencode_server import get_server
        alive = get_server()._is_port_in_use()
        if alive:
            OpenCodeExecutor._port_alive_until = time.time() + 30
        return alive

    async def _is_server_available(self) -> bool:
        """Check if OpenCode server is up (async-safe), with 30s TTL cache."""
        if time.time() < OpenCodeExecutor._port_alive_until:
            return True
        alive = await asyncio.to_thread(self._is_server_available_sync)
        return alive

    async def _run_opencode(self, instruction: str, timeout: int) -> Dict[str, Any]:
        """
        Run OpenCode to generate Python code.

        Tries the persistent HTTP server first (no Node.js cold-start overhead).
        Falls back to spawning a subprocess if the server is unavailable.

        Returns:
            Dict with keys: success, output, session_id, error
        """
        # --- HTTP server mode (fast path, with cached port check) ---
        if await self._is_server_available():
            print("[OPENCODE] Using HTTP server mode (no cold-start)")
            http_result = await self._run_opencode_http(instruction, timeout)
            if http_result["success"]:
                return http_result
            print(f"[OPENCODE] HTTP mode failed ({http_result.get('error')}), "
                  "falling back to subprocess")
            # Invalidate cache on failure
            OpenCodeExecutor._port_alive_until = 0

        # --- Subprocess fallback (run in thread to avoid blocking) ---
        print("[OPENCODE] Using subprocess mode")
        return await asyncio.to_thread(self._run_opencode_subprocess, instruction, timeout)

    def _run_opencode_subprocess(self, instruction: str, timeout: int) -> Dict[str, Any]:
        """Subprocess fallback — runs in a thread via asyncio.to_thread."""
        cmd = self._build_command(instruction)
        print(f"[OPENCODE] Command: {' '.join(cmd[:6])}...")

        stdout_lines = []
        stderr_lines = []

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(self.workspace),
                encoding='utf-8',
                errors='replace'
            )

            # Read stderr in background
            stderr_queue = queue.Queue()
            def read_stderr():
                for line in process.stderr:
                    stderr_queue.put(line)

            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stderr_thread.start()

            # Stream stdout
            deadline = time.time() + timeout
            for line in process.stdout:
                if time.time() > deadline:
                    process.kill()
                    raise subprocess.TimeoutExpired(cmd, timeout)

                stdout_lines.append(line)
                if self._debug_log_enabled():
                    self._log_stream_line(line.rstrip('\n\r'))

            # Wait for completion
            remaining = max(1, deadline - time.time())
            returncode = process.wait(timeout=remaining)

            # Collect stderr
            stderr_thread.join(timeout=0.2 if returncode == 0 else 1)
            while not stderr_queue.empty():
                stderr_lines.append(stderr_queue.get_nowait())

            # Parse output
            full_stdout = ''.join(stdout_lines)
            output_text, session_id, error_msg = self._parse_output(full_stdout)

            return {
                "success": returncode == 0 and error_msg is None,
                "output": output_text,
                "session_id": session_id,
                "error": error_msg
            }

        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except:
                pass
            return {
                "success": False,
                "output": ''.join(stdout_lines),
                "session_id": None,
                "error": f"OpenCode timeout after {timeout}s"
            }
        except Exception as e:
            return {
                "success": False,
                "output": ''.join(stdout_lines),
                "session_id": None,
                "error": f"OpenCode error: {str(e)}"
            }

    async def _run_opencode_http(self, instruction: str, timeout: int) -> Dict[str, Any]:
        """
        Run OpenCode via the persistent HTTP server.

        Always creates a fresh session per call — no context accumulation.
        Sessions are deleted after use (fire-and-forget) to prevent orphan buildup.
        This keeps prompt size constant regardless of how many times python_coder
        is called in a session, and allows parallel calls without serialization.

        Returns:
            Dict with keys: success, output, session_id, error
        """
        from tools.python_coder.opencode_server import get_server

        base_url = get_server().server_url
        client = self._get_http_client()

        # --- Always create a fresh session — no reuse, no context accumulation ---
        try:
            resp = await client.post(
                f"{base_url}/session",
                json={"title": f"llm-{self.session_id[:8]}"},
                timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
            )
            resp.raise_for_status()
            opencode_session_id = resp.json()["id"]
            print(f"[OPENCODE-HTTP] Created session: {opencode_session_id}")
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "session_id": None,
                "error": f"Failed to create OpenCode session: {e}",
            }

        # --- Send prompt, wait for full response; always clean up session ---
        try:
            provider, model = config.OPENCODE_MODEL.split("/", 1)
            resp = await client.post(
                f"{base_url}/session/{opencode_session_id}/message",
                json={
                    "model": {
                        "providerID": provider,
                        "modelID": model,
                    },
                    "parts": [{"type": "text", "text": instruction}],
                },
                timeout=httpx.Timeout(connect=10.0, read=timeout, write=10.0, pool=5.0),
            )
            resp.raise_for_status()
            result = resp.json()

            if self._debug_log_enabled():
                self._log_stage(f"RAW HTTP RESPONSE keys={list(result.keys())}")
                info = result.get("info", {})
                log_to_prompts_file(f"  info.finish={info.get('finish')}")
                log_to_prompts_file(f"  info.providerID={info.get('providerID')}")
                log_to_prompts_file(f"  info.modelID={info.get('modelID')}")

            # Check for OpenCode-level errors (HTTP 200 but execution failed)
            info = result.get("info", {})
            oc_error = info.get("error")
            if isinstance(oc_error, dict) and oc_error.get("data", {}).get("message"):
                error_msg = oc_error["data"]["message"].strip('"')
                self._log_stage(f"OpenCode error: {error_msg}")
                return {
                    "success": False,
                    "output": "",
                    "session_id": opencode_session_id,
                    "error": f"OpenCode error: {error_msg}",
                }

            text = self._extract_opencode_text(result)
            if len(text) > 3000:
                text = text[:3000] + "\n...[truncated]"
            if self._summary_log_enabled():
                self._log_stage(f"Extracted text ({len(text)} chars)")
                if self._debug_log_enabled():
                    for line in text.split('\n')[:40]:
                        log_to_prompts_file(f"  {line}")

            return {
                "success": True,
                "output": text,
                "session_id": opencode_session_id,
                "error": None,
            }

        except httpx.TimeoutException:
            return {
                "success": False,
                "output": "",
                "session_id": opencode_session_id,
                "error": f"OpenCode HTTP timeout after {timeout}s",
            }
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "session_id": opencode_session_id,
                "error": f"OpenCode HTTP error: {e}",
            }
        finally:
            # Fire-and-forget cleanup — delete session to avoid orphan accumulation
            asyncio.ensure_future(
                client.delete(f"{base_url}/session/{opencode_session_id}",
                              timeout=httpx.Timeout(5.0))
            )

    @staticmethod
    def _extract_opencode_text(result: Dict[str, Any]) -> str:
        """
        Extract the final assistant text from OpenCode HTTP response.
        This intentionally ignores reasoning parts to keep tool payload compact.
        """
        if isinstance(result.get("parts"), list):
            for part in reversed(result["parts"]):
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    text = part["text"].strip()
                    if text:
                        return text

        if isinstance(result.get("messages"), list):
            for message in reversed(result["messages"]):
                if not isinstance(message, dict):
                    continue
                if message.get("role") != "assistant":
                    continue
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
                parts = message.get("parts")
                if isinstance(parts, list):
                    for part in reversed(parts):
                        if isinstance(part, dict) and part.get("type") == "text":
                            text = part.get("text", "")
                            if isinstance(text, str) and text.strip():
                                return text.strip()

        for key in ("text", "output", "content", "result"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return ""

    async def _run_python_file(self, python_file: Path, timeout: int) -> Dict[str, Any]:
        """
        Run a Python file with streaming output capture.

        Returns:
            Dict with keys: stdout, stderr, returncode
        """
        print(f"[OPENCODE] Running: python {python_file.name}")
        log_to_prompts_file(f"  Executing: python {python_file.name}")

        try:
            result = await run_streaming(
                program=sys.executable,
                args=[python_file.name],
                cwd=str(self.workspace),
                timeout=timeout,
                max_output_size=self.max_output_size,
            )
        except Exception as e:
            return {
                "stdout": "",
                "stderr": f"Python execution error: {str(e)}",
                "returncode": -1,
            }

        if result.timed_out:
            return {
                "stdout": result.stdout,
                "stderr": f"Python execution timeout after {timeout}s",
                "returncode": -1,
            }

        log_to_prompts_file(f"  Return code: {result.returncode}")
        if result.stdout:
            log_to_prompts_file(f"  Stdout: {result.stdout[:500]}")
        if result.stderr:
            log_to_prompts_file(f"  Stderr: {result.stderr[:500]}")

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    def _build_command(self, instruction: str) -> List[str]:
        """Build opencode run command"""
        opencode_cmd = config.OPENCODE_PATH
        if sys.platform == "win32" and not opencode_cmd.endswith(".cmd"):
            opencode_cmd = f"{opencode_cmd}.cmd"

        # Instruction already has ULTRAWORK prefix from execute()
        # Use --format default (plain text) - more reliable than JSON parsing
        cmd = [
            opencode_cmd,
            "run",
            instruction,
            "--format", "default",
            "--model", config.OPENCODE_MODEL,
        ]

        return cmd

    def _parse_output(self, stdout: str) -> Tuple[str, Optional[str], Optional[str]]:
        """
        Parse OpenCode plain-text output (--format default).

        Strips ANSI escape codes and returns the clean text.
        Session ID is not extractable from plain text, so continuation
        is disabled (each call starts fresh, which is fine since workspace
        files persist between calls via the shared directory).

        Returns:
            Tuple of (text_output, opencode_session_id, error_message)
        """
        # Strip ANSI escape codes (colors, bold, etc.) — uses pre-compiled regex
        clean = _ANSI_ESCAPE_RE.sub('', stdout)

        # Strip other control characters except newlines/tabs
        clean = _CONTROL_CHAR_RE.sub('', clean)

        # Detect error lines
        error_msg = None
        for line in clean.split('\n'):
            stripped = line.strip()
            if stripped.lower().startswith('error:') or 'configuration is invalid' in stripped.lower():
                error_msg = stripped
                break

        return clean.strip(), None, error_msg

    def _get_python_files(self) -> List[Path]:
        """Get list of Python files in workspace"""
        try:
            return list(self.workspace.glob("*.py"))
        except Exception:
            return []

    def _relocate_stray_files(self, root_py_before: set, project_root: Path) -> int:
        """
        Move .py files that OpenCode's HTTP server wrote to the project root
        into self.workspace.  Only files that appeared DURING execution are moved.

        Returns the number of files relocated.
        """
        workspace_resolved = self.workspace.resolve()
        if project_root == workspace_resolved:
            return 0

        moved = 0
        try:
            new_files = set(project_root.glob("*.py")) - root_py_before
            for src in new_files:
                dest = self.workspace / src.name
                src.rename(dest)
                print(f"[OPENCODE] Relocated {src.name} -> {dest}")
                moved += 1
        except Exception as e:
            print(f"[OPENCODE] Warning: File relocation failed: {e}")

        return moved

    def _find_python_file_to_run(
        self, new_files: set, opencode_output: str, all_py_files: Optional[set] = None,
    ) -> Optional[Path]:
        """
        Find the Python file to run

        Priority:
        1. Newly created .py file
        2. File mentioned in OpenCode output
        3. Most recently modified .py file

        Args:
            new_files: Set of newly created/modified Path objects
            opencode_output: Raw OpenCode stdout text
            all_py_files: Optional pre-collected set of all .py files (avoids re-glob)
        """
        # Priority 1: New file created during this run
        if new_files:
            # If multiple, prefer the one mentioned in output
            for f in new_files:
                if f.name in opencode_output:
                    print(f"[OPENCODE] Found new file mentioned in output: {f.name}")
                    return f
            # Otherwise return the first new file
            file = next(iter(new_files))
            print(f"[OPENCODE] Found new file: {file.name}")
            return file

        # Priority 2: Extract filename from OpenCode output
        # Look for patterns like "saved to solution.py" or "created file.py"
        for pattern in _FILENAME_PATTERNS:
            matches = pattern.findall(opencode_output)
            for match in matches:
                file_path = self.workspace / match
                if file_path.exists():
                    print(f"[OPENCODE] Found file from output pattern: {match}")
                    return file_path

        # Priority 3: Most recently modified .py file (reuse already-collected set)
        py_files = list(all_py_files) if all_py_files else self._get_python_files()
        if py_files:
            py_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            print(f"[OPENCODE] Using most recent .py file: {py_files[0].name}")
            return py_files[0]

        return None

    def _combine_outputs(
        self,
        opencode_output: str,
        python_file: Path,
        python_stdout: str,
        python_stderr: str,
        python_returncode: int
    ) -> str:
        """Combine outputs from OpenCode and Python execution"""
        parts = []

        # OpenCode generation summary (HTTP path pre-truncates to 3000; cap subprocess too)
        if opencode_output:
            text = opencode_output if len(opencode_output) <= 3000 else opencode_output[:3000] + "\n...[truncated]"
            parts.append(f"[Code Generation]\n{text}")

        # Python execution output
        parts.append(f"\n[Execution: {python_file.name}]")

        if python_stdout:
            parts.append(python_stdout)

        if python_stderr and python_returncode != 0:
            parts.append(f"\n[Stderr]\n{python_stderr}")

        if python_returncode == 0:
            parts.append("\n[Execution completed successfully]")
        else:
            parts.append(f"\n[Execution failed with code {python_returncode}]")

        return "\n".join(parts)

    def _get_workspace_files(self) -> Dict[str, Any]:
        """Get list of files in workspace with metadata"""
        files = {}
        try:
            for file_path in self.workspace.iterdir():
                if file_path.is_file():
                    st = file_path.stat()
                    files[file_path.name] = {
                        "size": st.st_size,
                        "modified": st.st_mtime,
                        "path": str(file_path)
                    }
        except Exception as e:
            print(f"[OPENCODE] Warning: Failed to list files: {e}")
        return files

    def read_file(self, filename: str) -> Optional[str]:
        """Read a file from workspace"""
        file_path = self.workspace / filename
        if not file_path.exists():
            return None
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return None

    def list_files(self) -> List[str]:
        """List all files in workspace"""
        try:
            return [f.name for f in self.workspace.iterdir() if f.is_file()]
        except Exception:
            return []

    def clear_workspace(self) -> None:
        """Clear all files in workspace"""
        import shutil
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # Logging Methods
    # =========================================================================

    def _log_start(self, instruction: str, timeout: int) -> None:
        """Log execution start"""
        log_to_prompts_file("\n\n")
        log_to_prompts_file("=" * 80)
        log_to_prompts_file("TOOL EXECUTION: python_coder (OpenCode Two-Stage)")
        log_to_prompts_file("=" * 80)
        log_to_prompts_file(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log_to_prompts_file(f"Session ID: {self.session_id}")
        log_to_prompts_file(f"Workspace: {self.workspace}")
        log_to_prompts_file(f"Timeout: {timeout}s")
        log_to_prompts_file("")
        log_to_prompts_file("INSTRUCTION:")
        for line in instruction.split('\n'):
            log_to_prompts_file(f"  {line}")

        print(f"\n{'=' * 60}")
        print(f"[OPENCODE] Two-Stage Execution")
        print(f"{'=' * 60}")
        print(f"Session: {self.session_id}")
        print(f"Workspace: {self.workspace}")
        print(f"Instruction: {instruction[:100]}...")

    def _log_stage(self, stage_name: str) -> None:
        """Log stage separator"""
        log_to_prompts_file("")
        log_to_prompts_file("-" * 80)
        log_to_prompts_file(stage_name)
        log_to_prompts_file("-" * 80)

    def _log_stream_line(self, line: str) -> None:
        """Log a single line of plain-text streaming output"""
        # Uses pre-compiled regexes instead of recompiling per line
        clean = _ANSI_ESCAPE_RE.sub('', line)
        clean = _CONTROL_CHAR_RE.sub('', clean)
        if clean.strip():
            log_to_prompts_file(f"  {clean}")

    def _log_result(
        self,
        success: bool,
        returncode: int,
        execution_time: float,
        stdout: str,
        stderr: str,
        files: Dict[str, Any],
        error: Optional[str]
    ) -> None:
        """Log execution result"""
        log_to_prompts_file("")
        log_to_prompts_file("-" * 80)
        log_to_prompts_file("FINAL RESULT:")
        log_to_prompts_file(f"  Status: {'SUCCESS' if success else 'FAILED'}")
        log_to_prompts_file(f"  Return Code: {returncode}")
        log_to_prompts_file(f"  Execution Time: {execution_time:.2f}s")

        if stdout:
            log_to_prompts_file("")
            log_to_prompts_file("COMBINED OUTPUT:")
            for line in stdout.split('\n')[:50]:
                log_to_prompts_file(f"  {line}")

        if stderr:
            log_to_prompts_file("")
            log_to_prompts_file("STDERR:")
            for line in stderr.split('\n')[:20]:
                log_to_prompts_file(f"  {line}")

        if error:
            log_to_prompts_file("")
            log_to_prompts_file(f"ERROR: {error}")

        if files:
            log_to_prompts_file("")
            log_to_prompts_file("FILES:")
            for filename, meta in files.items():
                log_to_prompts_file(f"  {filename} ({meta['size']} bytes)")

        log_to_prompts_file("")
        log_to_prompts_file("=" * 80)

        # Console output
        print(f"\n{'=' * 60}")
        print(f"[OPENCODE] Completed in {execution_time:.2f}s")
        print(f"[OPENCODE] Success: {success}")
        if stdout:
            preview = stdout[:400] + "..." if len(stdout) > 400 else stdout
            print(f"[OPENCODE] Output:\n{preview}")
        if files:
            print(f"[OPENCODE] Files: {list(files.keys())}")
        print(f"{'=' * 60}")

    def _log_error(self, error_type: str, error_msg: str, execution_time: float) -> None:
        """Log execution error"""
        log_to_prompts_file("")
        log_to_prompts_file(f"ERROR: {error_type}")
        log_to_prompts_file(f"  {error_msg}")
        log_to_prompts_file(f"  Execution Time: {execution_time:.2f}s")
        log_to_prompts_file("")
        log_to_prompts_file("=" * 80)

        print(f"\n[OPENCODE] ERROR: {error_msg}")
