"""
Stop signal utility for halting in-flight LLM inference.

Usage:
  - Create data/STOP file to signal all running agent loops to stop
  - Delete data/STOP file (or restart servers) to resume normal operation
  - Use stop_inference.py script at project root for convenience
"""
import config


class StopInferenceError(Exception):
    """Raised when a stop signal is detected during inference."""
    pass


def is_stop_requested() -> bool:
    """Return True if the stop file exists."""
    return config.STOP_FILE.exists()


def check_stop():
    """Raise StopInferenceError if stop signal is active."""
    if is_stop_requested():
        raise StopInferenceError("Inference stopped — data/STOP file detected")


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
