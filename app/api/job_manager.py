"""In-memory job management and Server-Sent Events (SSE) broadcaster for DocuMend."""
import asyncio
from dataclasses import dataclass, field
import datetime
import logging
from typing import Any, Dict, Optional
import uuid

logger = logging.getLogger(__name__)


@dataclass
class JobState:
    """Tracks state and progress of an active document processing job."""

    job_id: str
    filename: str
    status: str = "pending"  # "pending", "processing", "completed", "failed"
    total_items: int = 0
    processed_items: int = 0
    current_snippet: str = ""
    error_message: Optional[str] = None
    result_bytes: Optional[bytes] = None
    stats: Optional[Dict[str, Any]] = None
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    events: asyncio.Queue = field(default_factory=asyncio.Queue)

    @property
    def progress_percent(self) -> int:
        if self.total_items == 0:
            return 0 if self.status != "completed" else 100
        return int((self.processed_items / self.total_items) * 100)


class JobManager:
    """Thread-safe and async-safe manager for document jobs."""

    def __init__(self):
        self._jobs: Dict[str, JobState] = {}
        self._lock = asyncio.Lock()

    async def create_job(self, filename: str) -> JobState:
        """Create and register a new job."""
        job_id = uuid.uuid4().hex[:12]
        job = JobState(job_id=job_id, filename=filename)
        async with self._lock:
            self._jobs[job_id] = job
            self._prune_stale_jobs()
        return job

    async def get_job(self, job_id: str) -> Optional[JobState]:
        """Retrieve a job by ID."""
        async with self._lock:
            return self._jobs.get(job_id)

    async def update_progress(
        self,
        job_id: str,
        processed: int,
        total: int,
        snippet: str,
        is_complete: bool = False,
    ):
        """Update job progress and broadcast an SSE event."""
        job = await self.get_job(job_id)
        if not job:
            return

        job.status = "completed" if is_complete else "processing"
        job.processed_items = processed
        job.total_items = total
        job.current_snippet = snippet

        event_data = {
            "job_id": job.job_id,
            "status": job.status,
            "processed": job.processed_items,
            "total": job.total_items,
            "percent": job.progress_percent,
            "snippet": job.current_snippet,
        }
        await job.events.put(event_data)

    async def complete_job(
        self,
        job_id: str,
        result_bytes: bytes,
        stats: Optional[Dict[str, Any]] = None,
    ):
        """Mark job as successfully completed with final document bytes and stats."""
        job = await self.get_job(job_id)
        if not job:
            return

        job.status = "completed"
        job.result_bytes = result_bytes
        job.processed_items = job.total_items
        job.stats = stats

        await job.events.put({
            "job_id": job.job_id,
            "status": "completed",
            "percent": 100,
            "processed": job.total_items,
            "total": job.total_items,
            "download_url": f"/api/jobs/{job.job_id}/download",
            "stats": stats,
        })

    async def fail_job(self, job_id: str, error_message: str):
        """Mark job as failed with an error message."""
        job = await self.get_job(job_id)
        if not job:
            return

        job.status = "failed"
        job.error_message = error_message

        await job.events.put({
            "job_id": job.job_id,
            "status": "failed",
            "error": error_message,
        })

    def _prune_stale_jobs(self, max_age_hours: int = 2):
        """Remove completed or failed jobs older than max_age_hours."""
        now = datetime.datetime.now()
        to_delete = []
        for jid, j in self._jobs.items():
            age = (now - j.created_at).total_seconds()
            if age > max_age_hours * 3600:
                to_delete.append(jid)
        for jid in to_delete:
            del self._jobs[jid]


job_manager = JobManager()
