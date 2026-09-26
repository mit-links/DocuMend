"""In-memory job management and Server-Sent Events (SSE) broadcaster for DocuMend."""

import asyncio
from dataclasses import dataclass, field
import datetime
import logging
from typing import Any, Optional
import uuid

logger = logging.getLogger(__name__)


@dataclass
class JobState:
    """Tracks state and progress of an active document processing job."""

    job_id: str
    filename: str
    status: str = "pending"  # "pending", "processing", "completed", "failed", "cancelled"
    total_items: int = 0
    processed_items: int = 0
    current_snippet: str = ""
    error_message: Optional[str] = None
    result_bytes: Optional[bytes] = None
    stats: Optional[dict[str, Any]] = None
    is_cancelled: bool = False
    task: Optional[asyncio.Task] = None
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    events: asyncio.Queue = field(default_factory=asyncio.Queue)
    _subscribers: set[asyncio.Queue] = field(default_factory=set, repr=False)

    @property
    def progress_percent(self) -> int:
        """Calculates integer completion percentage (0-100)."""
        if self.total_items == 0:
            return 0 if self.status != "completed" else 100
        return int((self.processed_items / self.total_items) * 100)

    def subscribe(self) -> asyncio.Queue:
        """Registers a new SSE listener queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Removes an SSE listener queue."""
        self._subscribers.discard(q)

    async def broadcast(self, event_data: dict[str, Any]) -> None:
        """Broadcasts event data to all active subscriber queues and legacy queue."""
        await self.events.put(event_data)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event_data)
            except asyncio.QueueFull:
                pass

    def to_event_dict(self) -> dict[str, Any]:
        """Serializes current job state into standard SSE event dictionary."""
        data: dict[str, Any] = {
            "job_id": self.job_id,
            "status": self.status,
            "processed": self.processed_items,
            "total": self.total_items,
            "percent": self.progress_percent,
            "snippet": self.current_snippet,
        }
        if self.status == "completed":
            data["download_url"] = f"/api/jobs/{self.job_id}/download"
            data["stats"] = self.stats
        elif self.status == "failed":
            data["error"] = self.error_message
        elif self.status == "cancelled":
            data["message"] = "Processing was stopped by user."
        return data

    def to_summary_dict(self) -> dict[str, Any]:
        """Serializes current job state into HTTP API details response dictionary."""
        return {
            "job_id": self.job_id,
            "filename": self.filename,
            "status": self.status,
            "total_items": self.total_items,
            "processed_items": self.processed_items,
            "percent": self.progress_percent,
            "error": self.error_message,
            "error_message": self.error_message,
            "stats": self.stats,
            "created_at": self.created_at.isoformat(),
        }


class JobManager:
    """Thread-safe and async-safe manager for document jobs."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}
        self._lock = asyncio.Lock()

    async def create_job(self, filename: str) -> JobState:
        """Creates and registers a new document processing job.

        Args:
            filename: Original filename of uploaded document.

        Returns:
            The created JobState instance.
        """
        job_id = uuid.uuid4().hex[:12]
        job = JobState(job_id=job_id, filename=filename)
        async with self._lock:
            self._jobs[job_id] = job
            self._prune_stale_jobs()
        return job

    async def get_job(self, job_id: str) -> Optional[JobState]:
        """Retrieves a job by its unique identifier.

        Args:
            job_id: Unique 12-char hex string job identifier.

        Returns:
            JobState if found, None otherwise.
        """
        async with self._lock:
            return self._jobs.get(job_id)

    async def update_progress(
        self,
        job_id: str,
        processed: int,
        total: int,
        snippet: str,
    ) -> None:
        """Updates job progress and broadcasts an SSE event.

        Args:
            job_id: Unique job identifier.
            processed: Number of items completed so far.
            total: Total number of items in document.
            snippet: Text preview of item being processed.
        """
        job = await self.get_job(job_id)
        # BUG-02 Fix: Do not overwrite terminal statuses (completed, failed, cancelled)
        if not job or job.is_cancelled or job.status in ("completed", "failed", "cancelled"):
            return

        job.status = "processing"
        job.processed_items = processed
        job.total_items = total
        job.current_snippet = snippet

        await job.broadcast(job.to_event_dict())

    async def complete_job(
        self,
        job_id: str,
        result_bytes: bytes,
        stats: Optional[dict[str, Any]] = None,
    ) -> None:
        """Marks job as successfully completed with final document bytes and stats.

        Args:
            job_id: Unique job identifier.
            result_bytes: Binary data of corrected DOCX document.
            stats: Performance and token usage statistics.
        """
        job = await self.get_job(job_id)
        if not job or job.is_cancelled or job.status in ("completed", "failed", "cancelled"):
            return

        job.status = "completed"
        job.result_bytes = result_bytes
        job.processed_items = job.total_items
        job.stats = stats

        await job.broadcast(job.to_event_dict())

    async def cancel_job(self, job_id: str) -> bool:
        """Cancels an active running job.

        Args:
            job_id: Unique job identifier.

        Returns:
            True if job was found and cancelled, False otherwise.
        """
        job = await self.get_job(job_id)
        if not job or job.status in ("completed", "failed", "cancelled"):
            return False

        job.is_cancelled = True
        job.status = "cancelled"

        if job.task and not job.task.done():
            job.task.cancel()

        await job.broadcast(job.to_event_dict())
        return True

    async def fail_job(self, job_id: str, error_message: str) -> None:
        """Marks job as failed with an error message.

        Args:
            job_id: Unique job identifier.
            error_message: Formatted, user-friendly error string.
        """
        job = await self.get_job(job_id)
        if not job or job.is_cancelled or job.status in ("completed", "failed", "cancelled"):
            return

        job.status = "failed"
        job.error_message = error_message

        await job.broadcast(job.to_event_dict())

    def _prune_stale_jobs(self, max_age_hours: int = 2) -> None:
        """Removes completed or failed jobs older than max_age_hours.

        Active jobs (processing/pending) are never pruned.
        """
        now = datetime.datetime.now()
        to_delete = []
        for jid, j in self._jobs.items():
            # BUG-14 Fix: Never prune active jobs
            if j.status not in ("completed", "failed", "cancelled"):
                continue
            age = (now - j.created_at).total_seconds()
            if age > max_age_hours * 3600:
                to_delete.append(jid)
        for jid in to_delete:
            del self._jobs[jid]


job_manager = JobManager()
