"""
Kernel-based Python executor using a persistent IPython kernel per session.

Variables, imports, and in-memory state persist across python_coder calls
within the same LLM session — the same model as OpenAI Code Interpreter and
smolagents DockerExecutor.

Architecture:
- One jupyter_client.AsyncKernelManager per LLM session_id (lazy start).
- Code is executed via kernel.execute() instead of a subprocess.
- stdout / execute_result / error collected from IOPub channel.
- Inherits NativePythonExecutor for code generation, retry loop,
  artifact checks, and logging — only _run_script is overridden.
- Falls back to native subprocess if kernel start fails or is not available.
- All kernels are shut down cleanly on server shutdown (hooked in app.py).
"""
import asyncio
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import config
from backend.utils.prompts_log_append import log_to_prompts_file
from tools.python_coder.native_tool import NativePythonExecutor

# ANSI colour codes produced by IPython tracebacks.
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[mGKHF]|\x1b\][^\x07]*\x07|\x1b[=><]')

# Class-level kernel registry: session_id -> (AsyncKernelManager, AsyncKernelClient)
# Asyncio is single-threaded so plain dict operations are safe between awaits.
_KERNELS: Dict[str, Tuple[Any, Any]] = {}


class KernelExecutor(NativePythonExecutor):
    """
    Persistent-kernel executor. Inherits full retry + artifact-check logic from
    NativePythonExecutor; only the execution layer uses a kernel instead of a
    fresh subprocess.
    """

    # ------------------------------------------------------------------
    # Override: execution via kernel
    # ------------------------------------------------------------------

    async def _run_script(self, script_name: str, exec_timeout: int, start_time: float) -> Dict[str, Any]:
        """Execute script in the session kernel; fall back to subprocess on error."""
        script_path = self.workspace / script_name
        try:
            code_text = script_path.read_text(encoding='utf-8')
        except Exception as e:
            return self._result_dict(
                success=False, script_name=script_name, executed=False,
                stdout="", stderr=str(e), returncode=-1,
                execution_time=time.time() - start_time,
                error=str(e),
            )

        # Ensure cwd is workspace so relative paths work.
        preamble = f"import os; os.chdir({str(self.workspace.resolve())!r})\n"
        full_code = preamble + code_text

        try:
            km, kc = await _get_or_start_kernel(self.session_id, self.workspace)
        except Exception as e:
            print(f"[KERNEL] Start failed ({e}), falling back to subprocess")
            log_to_prompts_file(f"[KERNEL] Fallback to subprocess: {e}")
            return await super()._run_script(script_name, exec_timeout, start_time)

        print(f"[KERNEL] Executing {script_name} in persistent kernel (session {self.session_id[:8]})")
        log_to_prompts_file(f"[KERNEL] execute {script_name}  timeout={exec_timeout}s")

        try:
            stdout, returncode = await asyncio.wait_for(
                _execute_in_kernel(kc, full_code),
                timeout=exec_timeout,
            )
        except asyncio.TimeoutError:
            # Restart the kernel so state is clean for the next attempt.
            await _restart_kernel(self.session_id, self.workspace)
            error_msg = f"Kernel execution timeout after {exec_timeout}s"
            execution_time = time.time() - start_time
            self._log_execution_error("TIMEOUT", error_msg, execution_time)
            return self._result_dict(
                success=False, script_name=script_name, executed=False,
                stdout="", stderr=error_msg, returncode=-1,
                execution_time=execution_time, error=error_msg,
            )
        except Exception as e:
            await _restart_kernel(self.session_id, self.workspace)
            error_msg = f"Kernel error: {e}"
            execution_time = time.time() - start_time
            return self._result_dict(
                success=False, script_name=script_name, executed=False,
                stdout="", stderr=error_msg, returncode=-1,
                execution_time=execution_time, error=error_msg,
            )

        execution_time = time.time() - start_time
        files = self._get_workspace_files()
        success = returncode == 0
        self._log_execution_result(success, returncode, execution_time, stdout, "", files)

        result = self._result_dict(
            success=success, script_name=script_name, executed=True,
            stdout=stdout, stderr="" if success else stdout,
            returncode=returncode,
            execution_time=execution_time,
            error=None if success else stdout,
        )
        result["execution_mode"] = "kernel"
        return result

    # ------------------------------------------------------------------
    # Class-level lifecycle
    # ------------------------------------------------------------------

    @classmethod
    async def shutdown_session(cls, session_id: str) -> None:
        """Shut down the kernel for a single session."""
        await _shutdown_kernel(session_id)

    @classmethod
    async def shutdown_all(cls) -> None:
        """Shut down every running kernel (called on server shutdown)."""
        for sid in list(_KERNELS):
            await _shutdown_kernel(sid)


# ------------------------------------------------------------------
# Module-level kernel helpers (not on the class; easier to mock/test)
# ------------------------------------------------------------------

async def _get_or_start_kernel(session_id: str, workspace: Path) -> Tuple[Any, Any]:
    if session_id in _KERNELS:
        km, kc = _KERNELS[session_id]
        if km.is_alive():
            return km, kc
        # Stale — restart.
        await _shutdown_kernel(session_id)

    from jupyter_client import AsyncKernelManager
    km = AsyncKernelManager()
    await km.start_kernel(cwd=str(workspace))
    kc = km.client()
    kc.start_channels()
    await asyncio.wait_for(kc.wait_for_ready(), timeout=30)
    _KERNELS[session_id] = (km, kc)
    print(f"[KERNEL] Started for session {session_id[:8]}")
    return km, kc


async def _restart_kernel(session_id: str, workspace: Path) -> None:
    await _shutdown_kernel(session_id)
    try:
        await _get_or_start_kernel(session_id, workspace)
    except Exception as e:
        print(f"[KERNEL] Restart failed: {e}")


async def _shutdown_kernel(session_id: str) -> None:
    if session_id not in _KERNELS:
        return
    km, kc = _KERNELS.pop(session_id)
    try:
        kc.stop_channels()
    except Exception:
        pass
    try:
        await km.shutdown_kernel(now=True)
    except Exception:
        pass
    print(f"[KERNEL] Shutdown for session {session_id[:8]}")


async def _execute_in_kernel(kc: Any, code: str) -> Tuple[str, int]:
    """Send code to the kernel, collect IOPub output, return (text, returncode).

    returncode: 0 = success, -1 = Python exception inside the kernel.
    """
    msg_id = kc.execute(code, store_history=True)
    outputs: List[str] = []
    error_lines: List[str] = []

    while True:
        try:
            msg = await asyncio.wait_for(kc.get_iopub_msg(), timeout=2.0)
        except asyncio.TimeoutError:
            # No message in 2 s — keep waiting (outer wait_for handles total deadline).
            continue
        except Exception:
            break

        if msg.get('parent_header', {}).get('msg_id') != msg_id:
            continue

        msg_type = msg['header']['msg_type']
        content = msg.get('content', {})

        if msg_type == 'stream':
            outputs.append(content.get('text', ''))
        elif msg_type == 'execute_result':
            text = content.get('data', {}).get('text/plain', '')
            if text:
                outputs.append(text + '\n')
        elif msg_type == 'display_data':
            # Include text representation if available.
            text = content.get('data', {}).get('text/plain', '')
            if text:
                outputs.append(f"[display] {text}\n")
        elif msg_type == 'error':
            tb = content.get('traceback', [])
            clean = [_ANSI_RE.sub('', line) for line in tb]
            error_lines = clean
        elif msg_type == 'status' and content.get('execution_state') == 'idle':
            break

    if error_lines:
        return '\n'.join(error_lines), -1
    return ''.join(outputs), 0
