"""Hermetic API endpoint unit tests for DocuMend.

Zero live network calls. All LLM and background worker operations are mocked.
Tests model querying, file uploads, concurrency validation, job cancellation,
SSE streaming, and download authorization.
"""

import io
import json
from unittest.mock import AsyncMock, patch
import docx
from fastapi.testclient import TestClient
import pytest

from app.api.job_manager import job_manager
from app.main import app

client = TestClient(app)


def make_valid_docx_bytes() -> bytes:
    """Generates valid .docx binary bytes in memory."""
    doc = docx.Document()
    doc.add_paragraph("Sample valid text")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# /api/models Tests
# ---------------------------------------------------------------------------

def test_ApiModels_WhenServerConnected_ReturnsModelsList():
    """Verify /api/models returns connected status and clean model list."""
    with patch("app.core.llm_client.LLMClient.list_models", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = ["qwen2.5-7b-instruct", "llama-3.1-8b"]
        response = client.get("/api/models?base_url=http://localhost:1234/v1")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "connected"
    assert data["models"] == ["qwen2.5-7b-instruct", "llama-3.1-8b"]


def test_ApiModels_WhenConnectionRefused_ReturnsCleanError():
    """Verify unreachable server returns status=error with formatted message."""
    with patch("app.core.llm_client.LLMClient.list_models", new_callable=AsyncMock) as mock_list:
        mock_list.side_effect = Exception("httpx.ConnectError: [Errno 111] Connection refused")
        response = client.get("/api/models?base_url=http://127.0.0.1:59999/v1")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "Connection refused" in data["error"]
    assert data["models"] == []


def test_ApiModels_WhenUnauthorized401_ReturnsInvalidApiKeyError():
    """Verify HTTP 401 returns clean unauthorized message."""
    with patch("app.core.llm_client.LLMClient.list_models", new_callable=AsyncMock) as mock_list:
        mock_list.side_effect = Exception("Error code: 401 - {'error': {'message': 'Invalid API Key'}}")
        response = client.get("/api/models?base_url=https://api.openai.com/v1")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "Invalid API Key" in data["error"]


# ---------------------------------------------------------------------------
# /api/process Upload Validation Tests
# ---------------------------------------------------------------------------

def test_ApiProcess_WhenNonDocxFileUploaded_Returns400():
    """Verify non-docx file is rejected with 400."""
    files = {"file": ("test.pdf", io.BytesIO(b"%PDF-1.4..."), "application/pdf")}
    response = client.post("/api/process", files=files)
    assert response.status_code == 400
    assert "Only Microsoft Word (.docx) documents are supported" in response.json()["detail"]


def test_ApiProcess_WhenEmptyFileUploaded_Returns400():
    """Verify 0-byte file is rejected with 400."""
    files = {
        "file": (
            "empty.docx",
            io.BytesIO(b""),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    response = client.post("/api/process", files=files)
    assert response.status_code == 400
    assert "uploaded file is empty" in response.json()["detail"]


def test_ApiProcess_WhenConcurrencyInvalid_ReturnsAppropriateHttpError():
    """Verify concurrency <= 0 returns 400, non-integer returns 422."""
    valid_bytes = make_valid_docx_bytes()
    valid_file = (
        "doc.docx",
        io.BytesIO(valid_bytes),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    # Concurrency = 0 -> 400
    res0 = client.post("/api/process", files={"file": valid_file}, data={"concurrency": "0"})
    assert res0.status_code == 400
    assert "positive integer" in res0.json()["detail"]

    # Concurrency = -1 -> 400
    valid_file_neg = (
        "doc.docx",
        io.BytesIO(valid_bytes),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    res_neg = client.post("/api/process", files={"file": valid_file_neg}, data={"concurrency": "-1"})
    assert res_neg.status_code == 400

    # Concurrency = 'invalid' -> 422 (FastAPI validation error)
    valid_file_inv = (
        "doc.docx",
        io.BytesIO(valid_bytes),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    res_invalid = client.post(
        "/api/process", files={"file": valid_file_inv}, data={"concurrency": "invalid"}
    )
    assert res_invalid.status_code == 422


def test_ApiProcess_ValidUpload_InitializesJobAndMocksWorker():
    """Verify valid upload creates pending job without leaking background network tasks."""
    valid_bytes = make_valid_docx_bytes()
    valid_file = (
        "doc.docx",
        io.BytesIO(valid_bytes),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    # Mock background runner so no real LLM worker is spawned
    with patch("app.api.routes._run_document_job", new_callable=AsyncMock):
        response = client.post(
            "/api/process",
            files={"file": valid_file},
            data={"concurrency": "2", "model": "test-model"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "pending"
    assert data["stream_url"] == f"/api/jobs/{data['job_id']}/stream"


# ---------------------------------------------------------------------------
# Job Lifecycle, Cancellation & Download Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ApiJobs_Lifecycle_DetailsCancellationAndDownload():
    """Hermetically verify job status transitions: pending -> cancelled -> download rejected."""
    job = await job_manager.create_job(filename="report.docx")

    # 1. Query job details
    details_res = client.get(f"/api/jobs/{job.job_id}")
    assert details_res.status_code == 200
    assert details_res.json()["status"] == "pending"

    # 2. Cancel the job
    cancel_res = client.post(f"/api/jobs/{job.job_id}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"
    assert cancel_res.json()["success"] is True

    # 3. Attempting to download cancelled job returns 400
    dl_res = client.get(f"/api/jobs/{job.job_id}/download")
    assert dl_res.status_code == 400
    assert "cancelled" in dl_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_ApiJobs_Download_WhenCompleted_ReturnsDocxAttachment():
    """Verify downloading a completed job returns the document bytes with attachment header."""
    job = await job_manager.create_job(filename="sample.docx")
    fake_docx_bytes = b"PK\x03\x04 fake docx binary data"
    await job_manager.complete_job(job.job_id, result_bytes=fake_docx_bytes, stats={"total_words": 100})

    res = client.get(f"/api/jobs/{job.job_id}/download")
    assert res.status_code == 200
    assert res.content == fake_docx_bytes
    assert "corrected_sample.docx" in res.headers["Content-Disposition"]


# ---------------------------------------------------------------------------
# SSE Stream Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ApiJobs_Stream_EmitsEventsAndTerminatesOnComplete():
    """Verify Server-Sent Events stream emits progress and terminates on completed status."""
    job = await job_manager.create_job(filename="stream_doc.docx")

    # Queue up progress and completion events
    await job_manager.update_progress(job.job_id, processed=1, total=2, snippet="Item 1")
    await job_manager.complete_job(job.job_id, result_bytes=b"output", stats={"words_per_second": 50})

    # Read SSE stream
    with client.stream("GET", f"/api/jobs/{job.job_id}/stream") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["Content-Type"]

        lines = [line for line in response.iter_lines() if line.startswith("data: ")]
        assert len(lines) >= 1

        first_event = json.loads(lines[0].removeprefix("data: "))
        assert first_event["job_id"] == job.job_id
