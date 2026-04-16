"""
Job store for background agent tasks.
Metadata is persisted in data/jobs/{job_id}.json.
Streamed output and tool events are append-only sidecar files.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from filelock import FileLock

import config


class JobStore:
    """Persist and query background job state."""

    def __init__(self, jobs_dir: Path = None):
        self.jobs_dir = jobs_dir or config.JOBS_DIR
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # File helpers
    # ------------------------------------------------------------------

    def _job_file(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def _lock_file(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.lock"

    def _output_file(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.output.txt"

    def _tool_events_file(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.events.jsonl"

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def create(
        self,
        job_id: str,
        username: str,
        session_id: str,
        model: str,
        temperature: float,
    ) -> Dict[str, Any]:
        """Write the initial job record to disk with status 'pending'."""
        job = {
            "job_id": job_id,
            "username": username,
            "session_id": session_id,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "started_at": None,
            "completed_at": None,
            "model": model,
            "temperature": temperature,
            "error": None,
            "output_length": 0,
            "tool_event_count": 0,
        }
        self._write(job_id, job)
        return job

    def load(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Load a job from disk. Returns None if not found."""
        path = self._job_file(job_id)
        if not path.exists():
            return None
        with FileLock(self._lock_file(job_id), timeout=10):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None

    def update_status(
        self,
        job_id: str,
        status: str,
        error: Optional[str] = None,
    ):
        """Update job status and timestamps."""
        with FileLock(self._lock_file(job_id), timeout=10):
            job = self._read_unlocked(job_id)
            if job is None:
                return
            job["status"] = status
            if status == "running" and job.get("started_at") is None:
                job["started_at"] = datetime.now().isoformat()
            if status in ("completed", "failed", "cancelled"):
                job["completed_at"] = datetime.now().isoformat()
            if error is not None:
                job["error"] = error
            self._write_unlocked(job_id, job)

    def append_chunk(self, job_id: str, text: str):
        """Append a text chunk to the job's output log."""
        if not text:
            return
        with FileLock(self._lock_file(job_id), timeout=10):
            job = self._read_unlocked(job_id)
            if job is None:
                return
            with open(self._output_file(job_id), "a", encoding="utf-8") as f:
                f.write(text)
            job["output_length"] = int(job.get("output_length", 0)) + len(text)
            self._write_unlocked(job_id, job)

    def append_tool_event(self, job_id: str, tool_name: str, status: str, duration: float = 0.0):
        """Append a tool status event to the job event log."""
        with FileLock(self._lock_file(job_id), timeout=10):
            job = self._read_unlocked(job_id)
            if job is None:
                return
            event = {
                "tool": tool_name,
                "status": status,
                "duration": duration,
                "at": datetime.now().isoformat(),
            }
            with open(self._tool_events_file(job_id), "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False))
                f.write("\n")
            job["tool_event_count"] = int(job.get("tool_event_count", 0)) + 1
            self._write_unlocked(job_id, job)

    def read_output(self, job_id: str) -> str:
        """Read the full accumulated output for a job."""
        with FileLock(self._lock_file(job_id), timeout=10):
            job = self._read_unlocked(job_id)
            if job is None:
                return ""

            output_file = self._output_file(job_id)
            if output_file.exists():
                return output_file.read_text(encoding="utf-8")

            return "".join(job.get("output_chunks", []))

    def read_output_since(self, job_id: str, offset: int = 0) -> Dict[str, Any]:
        """Read output starting at a byte offset."""
        with FileLock(self._lock_file(job_id), timeout=10):
            job = self._read_unlocked(job_id)
            if job is None:
                return {"content": "", "next_offset": offset}

            output_file = self._output_file(job_id)
            if output_file.exists():
                with open(output_file, "r", encoding="utf-8") as f:
                    safe_offset = max(0, offset)
                    f.seek(safe_offset)
                    content = f.read()
                    next_offset = f.tell()
                return {"content": content, "next_offset": next_offset}

            legacy_output = "".join(job.get("output_chunks", []))
            safe_offset = max(0, min(offset, len(legacy_output)))
            return {
                "content": legacy_output[safe_offset:],
                "next_offset": len(legacy_output),
            }

    def load_tool_events(self, job_id: str) -> List[Dict[str, Any]]:
        """Load all tool events for a job."""
        with FileLock(self._lock_file(job_id), timeout=10):
            job = self._read_unlocked(job_id)
            if job is None:
                return []

            events_file = self._tool_events_file(job_id)
            if events_file.exists():
                events: List[Dict[str, Any]] = []
                with open(events_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        events.append(json.loads(line))
                return events

            return job.get("tool_events", [])

    def list_jobs(self, username: str) -> List[Dict[str, Any]]:
        """List all jobs for a user (metadata only)."""
        jobs = []
        for path in sorted(self.jobs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if job.get("username") == username:
                    jobs.append(self._strip_output(job))
            except Exception:
                continue
        return jobs

    def delete(self, job_id: str) -> bool:
        """Delete all job artifacts from disk."""
        for path in (
            self._job_file(job_id),
            self._lock_file(job_id),
            self._output_file(job_id),
            self._tool_events_file(job_id),
        ):
            if path.exists():
                path.unlink()
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _write(self, job_id: str, job: Dict[str, Any]):
        with FileLock(self._lock_file(job_id), timeout=10):
            self._write_unlocked(job_id, job)

    def _write_unlocked(self, job_id: str, job: Dict[str, Any]):
        self._job_file(job_id).write_text(
            json.dumps(job, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _read_unlocked(self, job_id: str) -> Optional[Dict[str, Any]]:
        path = self._job_file(job_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def _strip_output(job: Dict[str, Any]) -> Dict[str, Any]:
        """Return job metadata without large legacy payloads."""
        summary = {
            k: v for k, v in job.items()
            if k not in {"output_chunks", "tool_events", "messages"}
        }
        if "output_length" not in summary:
            summary["output_length"] = sum(len(c) for c in job.get("output_chunks", []))
        if "tool_event_count" not in summary:
            summary["tool_event_count"] = len(job.get("tool_events", []))
        return summary


# Global instance
job_store = JobStore()
