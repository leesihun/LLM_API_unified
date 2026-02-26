"""
Job store for background agent tasks.
Jobs are persisted as JSON files in data/jobs/{job_id}.json.
Uses FileLock for safe concurrent reads/writes (same pattern as ConversationStore).
"""
import json
import threading
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

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def create(
        self,
        job_id: str,
        username: str,
        session_id: str,
        messages: List[Dict[str, Any]],
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
            "messages": messages,
            "output_chunks": [],
            "tool_events": [],
            "error": None,
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
        """Append a text chunk to the job's output."""
        with FileLock(self._lock_file(job_id), timeout=10):
            job = self._read_unlocked(job_id)
            if job is None:
                return
            job["output_chunks"].append(text)
            self._write_unlocked(job_id, job)

    def append_tool_event(self, job_id: str, tool_name: str, status: str, duration: float = 0.0):
        """Append a tool status event to the job record."""
        with FileLock(self._lock_file(job_id), timeout=10):
            job = self._read_unlocked(job_id)
            if job is None:
                return
            job["tool_events"].append({
                "tool": tool_name,
                "status": status,
                "duration": duration,
                "at": datetime.now().isoformat(),
            })
            self._write_unlocked(job_id, job)

    def list_jobs(self, username: str) -> List[Dict[str, Any]]:
        """List all jobs for a user (metadata only, no output_chunks)."""
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
        """Delete a job file from disk."""
        path = self._job_file(job_id)
        lock = self._lock_file(job_id)
        if path.exists():
            path.unlink()
        if lock.exists():
            lock.unlink()
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
        """Return job metadata without large output_chunks list."""
        summary = {k: v for k, v in job.items() if k != "output_chunks"}
        summary["output_length"] = sum(len(c) for c in job.get("output_chunks", []))
        return summary


# Global instance
job_store = JobStore()
