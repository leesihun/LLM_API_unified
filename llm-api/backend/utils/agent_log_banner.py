import threading


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
        print(f"[AGENT] Logging to: {resolved}", flush=True)
