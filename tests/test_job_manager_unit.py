"""Unit tests for JobManager and JobState in isolation.

Tests job registration, progress calculation, event queuing, pub/sub,
cancellation semantics, and stale job pruning.
"""

import asyncio
import datetime
import pytest

from app.api.job_manager import JobManager, JobState


@pytest.mark.asyncio
async def test_JobManager_CreateAndGetJob():
    """Verify job is created with 12-char ID and initial pending state."""
    jm = JobManager()
    job = await jm.create_job("document.docx")

    assert len(job.job_id) == 12
    assert job.filename == "document.docx"
    assert job.status == "pending"

    retrieved = await jm.get_job(job.job_id)
    assert retrieved is job


@pytest.mark.asyncio
async def test_JobManager_ProgressCalculation():
    """Verify progress percentage calculations under various states."""
    job = JobState(job_id="test1", filename="doc.docx", total_items=10, processed_items=5)
    assert job.progress_percent == 50

    # 0 total items while pending = 0%
    job_empty = JobState(job_id="test2", filename="doc.docx", total_items=0, status="pending")
    assert job_empty.progress_percent == 0

    # 0 total items while completed = 100%
    job_empty.status = "completed"
    assert job_empty.progress_percent == 100


@pytest.mark.asyncio
async def test_JobManager_CancelJob_CancelsTaskAndDispatchesEvent():
    """Verify cancel_job sets is_cancelled, cancels task, and dispatches SSE event."""
    jm = JobManager()
    job = await jm.create_job("doc.docx")

    async def dummy_task():
        await asyncio.sleep(10)

    task = asyncio.create_task(dummy_task())
    job.task = task

    success = await jm.cancel_job(job.job_id)
    assert success is True
    assert job.is_cancelled is True
    assert job.status == "cancelled"
    assert task.cancelling() > 0 or task.cancelled()

    # Event dispatched to queue
    event = await job.events.get()
    assert event["status"] == "cancelled"

    # Cancelling again returns False
    assert await jm.cancel_job(job.job_id) is False


@pytest.mark.asyncio
async def test_JobManager_PruneStaleJobs_RemovesOldJobsOnly():
    """Verify _prune_stale_jobs removes jobs older than max_age_hours."""
    jm = JobManager()
    job_fresh = await jm.create_job("fresh.docx")
    job_stale = await jm.create_job("stale.docx")

    # Only completed or failed jobs can be pruned
    job_stale.status = "completed"
    # Manually backdate stale job to 3 hours ago
    job_stale.created_at = datetime.datetime.now() - datetime.timedelta(hours=3)

    jm._prune_stale_jobs(max_age_hours=2)

    assert await jm.get_job(job_fresh.job_id) is not None
    assert await jm.get_job(job_stale.job_id) is None


@pytest.mark.asyncio
async def test_JobManager_PubSub_MultiSubscriber():
    """Verify JobState multi-subscriber pub/sub broadcasts to multiple queues."""
    job = JobState(job_id="pubsub_test", filename="test.docx")
    q1 = job.subscribe()
    q2 = job.subscribe()

    await job.broadcast({"test": "data"})

    ev1 = await q1.get()
    ev2 = await q2.get()
    assert ev1 == {"test": "data"}
    assert ev2 == {"test": "data"}

    job.unsubscribe(q1)
    await job.broadcast({"test": "data2"})
    assert q1.empty()
    ev2_next = await q2.get()
    assert ev2_next == {"test": "data2"}
