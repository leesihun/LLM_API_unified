"""
Stop signal utility for halting in-flight LLM inference.

Usage:
  - Create data/STOP file to signal ALL running agent loops to stop
  - Delete data/STOP file (or restart servers) to resume normal operation
  - Use stop_inference.py script at project root for convenience
  - Per-session: data/sessions/{session_id}.stop halts only that session's
    agent loop, without affecting anyone else. Self-clearing — the first
    check_stop() that observes the marker deletes it, so the *next* turn on
    that session isn't blocked too.
"""
import config


class StopInferenceError(Exception):
    """Raised when a stop signal is detected during inference."""
    pass


def is_stop_requested() -> bool:
    """Return True if the global stop file exists."""
    return config.STOP_FILE.exists()


def _session_stop_path(session_id: str):
    return config.SESSIONS_DIR / f"{session_id}.stop"


def check_stop(session_id: str = None):
    """Raise StopInferenceError if a global or per-session stop signal is active."""
    if is_stop_requested():
        raise StopInferenceError("Inference stopped — data/STOP file detected")
    if session_id and is_session_stop_requested(session_id):
        # Self-clearing: consume the marker now so the next turn on this
        # session starts clean instead of being stopped again immediately.
        try:
            _session_stop_path(session_id).unlink()
        except OSError:
            pass
        raise StopInferenceError(f"Inference stopped — session {session_id} stop requested")


def request_stop():
    """Create the stop file to signal running inference to halt."""
    config.STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.STOP_FILE.touch()
    print("[STOP] Stop file created — inference will halt at next checkpoint")


def clear_stop():
    """Remove the stop file to allow inference to proceed."""
    if config.STOP_FILE.exists():
        config.STOP_FILE.unlink()
        print("[STOP] Stop file removed")


def request_session_stop(session_id: str) -> None:
    """Signal a single session's agent loop to halt at its next checkpoint."""
    config.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    _session_stop_path(session_id).touch()
    print(f"[STOP] Session stop requested: {session_id}")


def is_session_stop_requested(session_id: str) -> bool:
    return _session_stop_path(session_id).exists()
