"""
Process Monitor Tool
Launch background processes, check status, read output incrementally, kill them.
Processes are scoped per session and tracked in an in-memory registry.
"""
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Optional, List

import config

MAX_BUFFER_LINES = getattr(config, "PROCESS_MONITOR_MAX_BUFFER_LINES", 5000)
MAX_PER_SESSION = getattr(config, "PROCESS_MONITOR_MAX_PER_SESSION", 20)
MAX_LINE_LENGTH = 4096
DEFAULT_READ_LINES = 200
DEAD_CLEANUP_SECONDS = 300  # Remove dead processes after 5 minutes


# ======================================================================
# ManagedProcess — state for one tracked background process
# ======================================================================

@dataclass
class ManagedProcess:
    handle: str
    command: str
    pid: int
    proc: subprocess.Popen
    started_at: float
    working_directory: str
    stdout_buf: deque = field(default_factory=lambda: deque(maxlen=MAX_BUFFER_LINES))
    stderr_buf: deque = field(default_factory=lambda: deque(maxlen=MAX_BUFFER_LINES))
    total_stdout_lines: int = 0
    total_stderr_lines: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


def _start_drain_threads(managed: ManagedProcess):
    """Spawn daemon threads that continuously drain stdout/stderr into ring buffers."""

    def drain(pipe, buf_attr: str, counter_attr: str):
        buf: deque = getattr(managed, buf_attr)
        while True:
            try:
                line = pipe.readline()
            except ValueError:
                break
            if not line:
                break
            if len(line) > MAX_LINE_LENGTH:
                line = line[:MAX_LINE_LENGTH] + "...[truncated]\n"
            with managed._lock:
                buf.append(line)
                setattr(managed, counter_attr, getattr(managed, counter_attr) + 1)

    t_out = threading.Thread(
        target=drain,
        args=(managed.proc.stdout, "stdout_buf", "total_stdout_lines"),
        daemon=True,
    )
    t_err = threading.Thread(
        target=drain,
        args=(managed.proc.stderr, "stderr_buf", "total_stderr_lines"),
        daemon=True,
    )
    t_out.start()
    t_err.start()


# ======================================================================
# ProcessRegistry — module-level singleton
# ======================================================================

class ProcessRegistry:
    """Thread-safe registry mapping (session_id, handle) -> ManagedProcess."""

    def __init__(self):
        self._lock = threading.Lock()
        self._processes: Dict[str, Dict[str, ManagedProcess]] = {}
        self._counters: Dict[str, int] = {}

    def register(self, session_id: str, proc: subprocess.Popen,
                 command: str, cwd: str) -> str:
        with self._lock:
            if session_id not in self._processes:
                self._processes[session_id] = {}
                self._counters[session_id] = 0
            self._counters[session_id] += 1
            handle = f"proc_{self._counters[session_id]}"
            managed = ManagedProcess(
                handle=handle,
                command=command,
                pid=proc.pid,
                proc=proc,
                started_at=time.time(),
                working_directory=cwd,
            )
            self._processes[session_id][handle] = managed
            return handle

    def get(self, session_id: str, handle: str) -> Optional[ManagedProcess]:
        with self._lock:
            return self._processes.get(session_id, {}).get(handle)

    def remove(self, session_id: str, handle: str) -> bool:
        with self._lock:
            session = self._processes.get(session_id, {})
            if handle in session:
                del session[handle]
                return True
            return False

    def list_for_session(self, session_id: str) -> List[ManagedProcess]:
        with self._lock:
            return list(self._processes.get(session_id, {}).values())

    def cleanup_dead(self, session_id: str):
        """Remove entries for processes that exited more than DEAD_CLEANUP_SECONDS ago."""
        now = time.time()
        with self._lock:
            session = self._processes.get(session_id, {})
            to_remove = []
            for handle, managed in session.items():
                if managed.proc.poll() is not None:
                    exited_duration = now - managed.started_at
                    if exited_duration > DEAD_CLEANUP_SECONDS:
                        to_remove.append(handle)
            for handle in to_remove:
                del session[handle]


# Module-level singleton
_registry = ProcessRegistry()


# ======================================================================
# ProcessMonitorTool
# ======================================================================

class ProcessMonitorTool:
    """Manage background processes for a session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.workspace = config.SCRATCH_DIR / session_id
        self.workspace.mkdir(parents=True, exist_ok=True)

    def execute(self, operation: str, **kwargs) -> Dict[str, Any]:
        if operation == "start":
            return self._start(kwargs.get("command"), kwargs.get("working_directory"))
        elif operation == "status":
            return self._status(kwargs.get("handle", ""))
        elif operation == "read_output":
            return self._read_output(
                kwargs.get("handle", ""),
                offset=kwargs.get("offset"),
                max_lines=kwargs.get("max_lines", DEFAULT_READ_LINES),
                stream=kwargs.get("stream", "both"),
            )
        elif operation == "kill":
            return self._kill(kwargs.get("handle", ""))
        elif operation == "list":
            return self._list()
        else:
            return {"success": False, "error": f"Unknown operation: {operation}"}

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def _start(self, command: Optional[str], working_directory: Optional[str]) -> Dict[str, Any]:
        if not command:
            return {"success": False, "error": "command is required for 'start' operation."}

        # Lazy cleanup of dead processes
        _registry.cleanup_dead(self.session_id)

        # Enforce per-session limit
        existing = _registry.list_for_session(self.session_id)
        alive = [p for p in existing if p.proc.poll() is None]
        if len(alive) >= MAX_PER_SESSION:
            return {
                "success": False,
                "error": f"Limit of {MAX_PER_SESSION} concurrent background processes reached. "
                         f"Kill a process first.",
            }

        cwd = self._resolve_working_directory(working_directory)
        cwd.mkdir(parents=True, exist_ok=True)

        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as e:
            return {"success": False, "error": f"Failed to start process: {e}"}

        handle = _registry.register(self.session_id, proc, command, str(cwd))
        managed = _registry.get(self.session_id, handle)
        _start_drain_threads(managed)

        return {
            "success": True,
            "handle": handle,
            "pid": proc.pid,
            "command": command,
            "working_directory": str(cwd),
        }

    def _status(self, handle: str) -> Dict[str, Any]:
        managed = _registry.get(self.session_id, handle)
        if not managed:
            return {"success": False, "error": f"No process with handle '{handle}' in this session."}

        exit_code = managed.proc.poll()
        running = exit_code is None
        uptime = time.time() - managed.started_at

        return {
            "success": True,
            "handle": handle,
            "pid": managed.pid,
            "command": managed.command,
            "running": running,
            "exit_code": exit_code,
            "uptime_seconds": round(uptime, 1),
            "total_stdout_lines": managed.total_stdout_lines,
            "total_stderr_lines": managed.total_stderr_lines,
        }

    def _read_output(self, handle: str, offset: Optional[int],
                     max_lines: int, stream: str) -> Dict[str, Any]:
        managed = _registry.get(self.session_id, handle)
        if not managed:
            return {"success": False, "error": f"No process with handle '{handle}' in this session."}

        result: Dict[str, Any] = {"success": True, "handle": handle}

        with managed._lock:
            if stream in ("stdout", "both"):
                result["stdout"] = self._extract_lines(
                    managed.stdout_buf, managed.total_stdout_lines, offset, max_lines,
                )
            if stream in ("stderr", "both"):
                result["stderr"] = self._extract_lines(
                    managed.stderr_buf, managed.total_stderr_lines, offset, max_lines,
                )

        return result

    def _kill(self, handle: str) -> Dict[str, Any]:
        managed = _registry.get(self.session_id, handle)
        if not managed:
            return {"success": False, "error": f"No process with handle '{handle}' in this session."}

        if managed.proc.poll() is not None:
            return {
                "success": True,
                "handle": handle,
                "already_exited": True,
                "exit_code": managed.proc.returncode,
            }

        managed.proc.terminate()
        try:
            managed.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            managed.proc.kill()
            try:
                managed.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

        return {
            "success": True,
            "handle": handle,
            "killed": True,
            "exit_code": managed.proc.returncode,
        }

    def _list(self) -> Dict[str, Any]:
        _registry.cleanup_dead(self.session_id)
        procs = _registry.list_for_session(self.session_id)
        entries = []
        for m in procs:
            exit_code = m.proc.poll()
            entries.append({
                "handle": m.handle,
                "pid": m.pid,
                "command": m.command[:100],
                "running": exit_code is None,
                "exit_code": exit_code,
                "uptime_seconds": round(time.time() - m.started_at, 1),
            })
        return {"success": True, "processes": entries}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_lines(buf: deque, total: int, offset: Optional[int],
                       max_lines: int) -> Dict[str, Any]:
        """Extract lines from a ring buffer with offset tracking."""
        buf_list = list(buf)
        oldest_available = total - len(buf_list)

        if offset is None:
            # Tail mode: return the last max_lines
            lines = buf_list[-max_lines:] if len(buf_list) > max_lines else buf_list
            start_offset = total - len(lines)
            return {
                "lines": "".join(lines),
                "start_offset": start_offset,
                "next_offset": total,
                "total_lines": total,
            }

        if offset < oldest_available:
            # Requested lines have been evicted from the ring buffer
            gap = oldest_available - offset
            lines = buf_list[:max_lines]
            return {
                "lines": "".join(lines),
                "start_offset": oldest_available,
                "next_offset": oldest_available + len(lines),
                "total_lines": total,
                "gap_lines": gap,
                "note": f"{gap} lines were evicted from the buffer before they could be read.",
            }

        buf_offset = offset - oldest_available
        lines = buf_list[buf_offset:buf_offset + max_lines]
        return {
            "lines": "".join(lines),
            "start_offset": offset,
            "next_offset": offset + len(lines),
            "total_lines": total,
        }

    def _resolve_working_directory(self, working_directory: Optional[str]) -> Path:
        if not working_directory:
            return self.workspace.resolve()
        cwd = Path(working_directory).expanduser()
        if cwd.is_absolute():
            return cwd.resolve()
        return (Path.cwd() / cwd).resolve()
