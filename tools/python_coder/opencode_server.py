"""
OpenCode Server Manager
Manages the lifecycle of opencode persistent server
"""
import subprocess
import time
import threading
from typing import Optional

import config


class OpenCodeServerManager:
    """
    Singleton manager for opencode server lifecycle

    Responsibilities:
    - Start server on initialization
    - Auto-restart once on failure
    - Provide server URL for executors
    """

    _instance: Optional["OpenCodeServerManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "OpenCodeServerManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._process: Optional[subprocess.Popen] = None
        self._restart_attempted = False
        self._server_url = f"http://{config.OPENCODE_SERVER_HOST}:{config.OPENCODE_SERVER_PORT}"
        self._initialized = True

    @property
    def server_url(self) -> str:
        """Get server URL for --attach flag"""
        return self._server_url

    @property
    def is_running(self) -> bool:
        """Check if server process is running"""
        if self._process is None:
            return False
        return self._process.poll() is None

    def start(self) -> None:
        """
        Start opencode server

        Raises:
            RuntimeError: If server fails to start
        """
        if self.is_running:
            print(f"[OPENCODE SERVER] Already running on {self._server_url}")
            return

        # Check if port is already in use (external server already running)
        if self._is_port_in_use():
            print(f"[OPENCODE SERVER] Port {config.OPENCODE_SERVER_PORT} already in use")
            print(f"[OPENCODE SERVER] Assuming external server is running on {self._server_url}")
            return

        print(f"[OPENCODE SERVER] Starting on port {config.OPENCODE_SERVER_PORT}...")

        # On Windows, use .cmd extension for npm global binaries
        import sys
        opencode_cmd = config.OPENCODE_PATH
        if sys.platform == "win32" and not opencode_cmd.endswith(".cmd"):
            opencode_cmd = f"{opencode_cmd}.cmd"

        cmd = [
            opencode_cmd,
            "serve",
            "--port", str(config.OPENCODE_SERVER_PORT),
            "--hostname", config.OPENCODE_SERVER_HOST,
        ]

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Wait for server to be ready (max 30 seconds)
        ready, error_msg = self._wait_for_server(timeout=30)
        if not ready:
            # Get process output for debugging
            stderr_output = ""
            if self._process.stderr:
                try:
                    stderr_output = self._process.stderr.read(1000)  # Read first 1000 chars
                except:
                    pass

            self._process.terminate()
            self._process = None

            error_detail = f"OpenCode server failed to start on {self._server_url}."
            if stderr_output:
                error_detail += f"\n\nServer output:\n{stderr_output}"
            if error_msg:
                error_detail += f"\n\nError: {error_msg}"
            error_detail += "\n\nCheck if opencode is installed: npm install -g opencode-ai@latest"

            raise RuntimeError(error_detail)

        print(f"[OPENCODE SERVER] Running on {self._server_url}")

    def _is_port_in_use(self) -> bool:
        """Check if the opencode server port is already in use"""
        import socket

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((config.OPENCODE_SERVER_HOST, config.OPENCODE_SERVER_PORT))
            sock.close()
            return result == 0  # Port is in use if connection succeeds
        except Exception:
            return False

    def _wait_for_server(self, timeout: int) -> tuple[bool, str]:
        """
        Wait for server to be ready

        Returns:
            Tuple of (is_ready, error_message)
        """
        import socket

        start = time.time()
        last_error = ""

        while time.time() - start < timeout:
            # Check if process is still alive
            if self._process and self._process.poll() is not None:
                return False, f"Server process terminated with code {self._process.returncode}"

            # Try to connect to port (more reliable than HTTP endpoint)
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((config.OPENCODE_SERVER_HOST, config.OPENCODE_SERVER_PORT))
                sock.close()

                if result == 0:
                    # Port is open, server is ready
                    return True, ""

            except Exception as e:
                last_error = str(e)

            time.sleep(0.5)

        return False, f"Timeout after {timeout}s. Last error: {last_error}"

    def stop(self) -> None:
        """Stop opencode server"""
        if self._process is not None:
            print("[OPENCODE SERVER] Stopping...")
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
            print("[OPENCODE SERVER] Stopped")

    def ensure_running(self) -> None:
        """
        Ensure server is running, restart once if needed

        Raises:
            RuntimeError: If server is down and restart fails
        """
        if self.is_running:
            return

        if self._restart_attempted:
            raise RuntimeError(
                "OpenCode server is down and restart already attempted. "
                "Manual intervention required."
            )

        print("[OPENCODE SERVER] Server down, attempting restart...")
        self._restart_attempted = True
        self.start()
        self._restart_attempted = False  # Reset on successful restart


# Global instance
_server_manager: Optional[OpenCodeServerManager] = None


def get_server_manager() -> OpenCodeServerManager:
    """Get the global server manager instance"""
    global _server_manager
    if _server_manager is None:
        _server_manager = OpenCodeServerManager()
    return _server_manager


def start_opencode_server() -> None:
    """
    Ensure the opencode server is running (call on tools_server startup).

    Auto-starts the server process if not already running.  On failure the
    warning is printed and tool calls fall back to per-request subprocess mode.
    """
    from tools.python_coder.opencode_config import ensure_opencode_config

    # Keep opencode config in sync with config.py
    ensure_opencode_config()

    manager = get_server_manager()
    try:
        manager.start()
    except RuntimeError as e:
        print(f"[OPENCODE SERVER] WARNING: {e}")
        print("[OPENCODE SERVER] Tool calls will fall back to subprocess mode")


def get_server() -> OpenCodeServerManager:
    """Convenience alias used by opencode_tool.py."""
    return get_server_manager()


def stop_opencode_server() -> None:
    """Stop the opencode server (call on tools_server shutdown)"""
    global _server_manager
    if _server_manager is not None:
        _server_manager.stop()
        _server_manager = None
