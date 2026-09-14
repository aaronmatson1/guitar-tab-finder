"""A small background-job registry.

Analysing a song takes tens of seconds, which is far too long to hold a
request open. Work is handed to a worker thread and the browser polls for the
result. This is deliberately minimal: the app is a local single-user tool, not
a service, so there is no broker and no persistence.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

#: Finished jobs are kept this long so a slow browser can still collect them.
RETENTION_SECONDS = 30 * 60

#: Jobs kept in memory at once, oldest evicted first.
MAX_JOBS = 40


@dataclass
class Job:
    """One unit of background work and whatever became of it."""

    id: str
    kind: str
    status: str = "pending"          # pending | running | done | error
    progress: str = ""
    result: Optional[Any] = None
    error: Optional[str] = None
    created: float = field(default_factory=time.time)
    finished: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": self.progress,
            "elapsed": round((self.finished or time.time()) - self.created, 1),
        }
        if self.status == "done":
            payload["result"] = self.result
        if self.status == "error":
            payload["error"] = self.error
        return payload


class JobRegistry:
    """Runs callables on worker threads and remembers what they returned."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, work: Callable[["Job"], Any]) -> Job:
        """Start ``work`` on a thread. It is handed the job so it can report progress."""
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._evict()
            self._jobs[job.id] = job

        def run() -> None:
            job.status = "running"
            try:
                job.result = work(job)
                job.status = "done"
            except Exception as exc:  # noqa: BLE001 - surfaced to the browser
                job.status = "error"
                job.error = _explain(exc)
                traceback.print_exc()
            finally:
                job.finished = time.time()

        threading.Thread(target=run, daemon=True, name=f"tabfinder-{kind}").start()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def _evict(self) -> None:
        """Forget jobs that are old or surplus. Callers hold the lock."""
        now = time.time()
        stale = [
            key for key, job in self._jobs.items()
            if job.finished and now - job.finished > RETENTION_SECONDS
        ]
        for key in stale:
            del self._jobs[key]
        if len(self._jobs) >= MAX_JOBS:
            oldest = sorted(self._jobs.values(), key=lambda j: j.created)
            for job in oldest[: len(self._jobs) - MAX_JOBS + 1]:
                self._jobs.pop(job.id, None)


def _explain(exc: Exception) -> str:
    """A message worth showing a person, not a stack trace."""
    text = str(exc).strip()
    return text or f"{type(exc).__name__} (no further detail)"
