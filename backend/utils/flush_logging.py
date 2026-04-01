"""Logging handlers that flush after each record so tail -f and editors see lines immediately."""
import logging
import threading


class FlushFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


def attach_flush_file_handler(logger: logging.Logger, path, level: int = logging.INFO) -> None:
    if logger.handlers:
        return
    h = FlushFileHandler(path, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(h)
    logger.setLevel(level)
    logger.propagate = False


_agent_log_banner_lock = threading.Lock()
_agent_log_banner_printed = False


def print_agent_log_banner_once(agent_log_path) -> None:
    global _agent_log_banner_printed
    with _agent_log_banner_lock:
        if _agent_log_banner_printed:
            return
        _agent_log_banner_printed = True
        try:
            resolved = agent_log_path.resolve()
        except Exception:
            resolved = agent_log_path
        print(f"[AGENT] Agent activity log: {resolved}", flush=True)
