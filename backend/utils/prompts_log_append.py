"""
Append to prompts.log with a hard line cap (FIFO rotation).

Strategy: always open in append mode (fast). Check line count every
_ROTATION_INTERVAL appends; when over cap, rewrite keeping the newest
80 % of lines. This amortises the expensive rewrite across many calls
instead of doing it on every single write.
"""
from __future__ import annotations

import logging
import os
from collections import deque
from pathlib import Path
from typing import Iterator, Optional

from filelock import FileLock

import config

# ── module-level rotation state (per process) ────────────────────────────────
_append_counter: int = 0
_ROTATION_INTERVAL: int = 100   # check size every N appends


def _prompts_lock_path(log_path: Path) -> Path:
    return log_path.with_name(log_path.name + ".lock")


def _iter_line_chunks(text: str) -> Iterator[str]:
    if not text:
        return
    for chunk in text.splitlines(keepends=True):
        yield chunk


def _rotate_if_needed(path: Path, max_lines: int) -> None:
    """Read the file, keep the newest 80 % of lines, rewrite atomically."""
    if not path.exists() or path.stat().st_size == 0:
        return
    keep = int(max_lines * 0.8)
    dq: deque[str] = deque(maxlen=keep)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            dq.append(line)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.writelines(dq)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp), str(path))
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def append_capped_prompts_log(text: str, path: Optional[Path] = None) -> None:
    """
    Append *text* to the log file.

    Normal path: just open(path, 'a') and write — O(len(text)).
    Every _ROTATION_INTERVAL calls: check whether the file exceeds
    PROMPTS_LOG_MAX_LINES and rotate if so.
    """
    global _append_counter

    path = path or config.PROMPTS_LOG_PATH
    path = Path(path)
    if not text:
        return

    max_lines = int(getattr(config, "PROMPTS_LOG_MAX_LINES", 100_000))
    cap_applies = path.resolve() == Path(config.PROMPTS_LOG_PATH).resolve()

    lock = FileLock(_prompts_lock_path(path), timeout=120)
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)

        # Fast path: just append
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
            f.flush()

        if not cap_applies:
            return

        # Periodic rotation check
        _append_counter += 1
        if _append_counter % _ROTATION_INTERVAL == 0:
            try:
                line_count = sum(1 for _ in open(path, "r", encoding="utf-8", errors="replace"))
                if line_count > max_lines:
                    _rotate_if_needed(path, max_lines)
            except Exception:
                pass  # Never break the caller over a log rotation failure


def log_to_prompts_file(message: str) -> None:
    """Append one logical log record (adds a trailing newline if missing)."""
    try:
        if not message:
            return
        chunk = message if message.endswith("\n") else message + "\n"
        append_capped_prompts_log(chunk)
    except Exception as e:
        print(f"[WARNING] Failed to write to prompts.log: {e}")


class CappedPromptsLogHandler(logging.Handler):
    """logging.Handler that writes to prompts.log with the same line cap + lock."""

    def __init__(self, log_path: Optional[Path] = None):
        super().__init__()
        self.log_path = Path(log_path or config.PROMPTS_LOG_PATH)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            line = msg if msg.endswith("\n") else msg + "\n"
            append_capped_prompts_log(line, path=self.log_path)
        except Exception:
            self.handleError(record)


def attach_capped_prompts_handler(logger: logging.Logger, path: Optional[Path] = None) -> None:
    if logger.handlers:
        return
    h = CappedPromptsLogHandler(path or config.PROMPTS_LOG_PATH)
    h.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
    logger.propagate = False
