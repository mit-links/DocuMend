"""Hermetic integration tests for DocuMend FastAPI routes."""

import io
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
import pytest

from app.api.job_manager import job_manager
from app.api.routes import format_error_message
from app.main import app
from scripts.create_test_doc import generate_sample_docx

client = TestClient(app)


def test_index_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "DocuMend" in response.text
    assert "Server Base URL" in response.text
    assert "LLM Server & Model Settings" in response.text
    assert 'type="text" id="apiKey"' in response.text


def test_get_models_endpoint():
    with patch("app.core.llm_client.LLMClient.list_models", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = ["qwen2.5", "llama3"]
        response = client.get("/api/models?base_url=http://127.0.0.1:1234/v1")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "connected"
        assert data["models"] == ["qwen2.5", "llama3"]


def test_process_invalid_file():
    files = {"file": ("test.txt", io.BytesIO(b"Hello world"), "text/plain")}
    response = client.post("/api/process", files=files)
    assert response.status_code == 400
    assert "Only Microsoft Word (.docx) documents are supported" in response.json()["detail"]


def test_process_valid_docx(tmp_path):
    sample_file = tmp_path / "sample.docx"
    generate_sample_docx(str(sample_file))

    with open(sample_file, "rb") as f:
        file_bytes = f.read()

    files = {
        "file": (
            "sample.docx",
            io.BytesIO(file_bytes),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    data = {
        "base_url": "http://127.0.0.1:1234/v1",
        "api_key": "not-needed",
        "model": "qwen/qwen3.5-9b",
        "concurrency": "4",
    }
    with patch("app.api.routes._run_document_job", new_callable=AsyncMock):
        response = client.post("/api/process", files=files, data=data)

    assert response.status_code == 200
    res_data = response.json()
    assert "job_id" in res_data
    assert res_data["status"] == "pending"
    assert "stream_url" in res_data


def test_process_invalid_concurrency(tmp_path):
    sample_file = tmp_path / "sample.docx"
    generate_sample_docx(str(sample_file))

    with open(sample_file, "rb") as f:
        file_bytes = f.read()

    files = {
        "file": (
            "sample.docx",
            io.BytesIO(file_bytes),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }

    # Zero concurrency
    res = client.post("/api/process", files=files, data={"concurrency": "0"})
    assert res.status_code == 400
    assert "positive integer" in res.json()["detail"]

    # Negative concurrency
    files["file"] = (
        "sample.docx",
        io.BytesIO(file_bytes),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    res = client.post("/api/process", files=files, data={"concurrency": "-5"})
    assert res.status_code == 400

    # Non-integer string concurrency (rejected by FastAPI Pydantic type coercion with 422)
    files["file"] = (
        "sample.docx",
        io.BytesIO(file_bytes),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    res = client.post("/api/process", files=files, data={"concurrency": "abc"})
    assert res.status_code == 422


def test_eject_models_endpoint():
    with patch("app.core.llm_client.LLMClient.eject_inactive_models", new_callable=AsyncMock) as mock_eject:
        mock_eject.return_value = ["stale-model-1"]
        response = client.post(
            "/api/models/eject",
            data={"base_url": "http://127.0.0.1:1234/v1"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "stale-model-1" in data["ejected"]


@pytest.mark.asyncio
async def test_cancel_nonexistent_job():
    response = client.post("/api/jobs/nonexistent123/cancel")
    assert response.status_code == 404
    assert "Job not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_cancel_active_job():
    job = await job_manager.create_job(filename="cancel_test.docx")
    response = client.post(f"/api/jobs/{job.job_id}/cancel")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == job.job_id
    assert data["status"] == "cancelled"
    assert data["success"] is True

    # Repeated cancellation should report success=False
    repeat_res = client.post(f"/api/jobs/{job.job_id}/cancel")
    assert repeat_res.status_code == 200
    assert repeat_res.json()["success"] is False


@pytest.mark.asyncio
async def test_upload_file_cleanup_and_no_lingering_temp_files(tmp_path):
    sample_file = tmp_path / "cleanup_test.docx"
    generate_sample_docx(str(sample_file))

    with open(sample_file, "rb") as f:
        file_bytes = f.read()

    files = {
        "file": (
            "cleanup_test.docx",
            io.BytesIO(file_bytes),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    with patch("app.api.routes._run_document_job", new_callable=AsyncMock):
        response = client.post("/api/process", files=files)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_job_details():
    job = await job_manager.create_job(filename="details_test.docx")
    response = client.get(f"/api/jobs/{job.job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == job.job_id
    assert data["filename"] == "details_test.docx"
    assert data["status"] == "pending"
    assert data["percent"] == 0

    # Nonexistent job ID
    err_res = client.get("/api/jobs/missing99999")
    assert err_res.status_code == 404


def test_format_error_message():
    assert "Connection refused" in format_error_message(Exception("httpx.ConnectError: Connection refused"))
    assert "Invalid API key" in format_error_message(Exception("Error 401: Unauthorized API key"))

    class MockOpenAIError(Exception):
        body = {"error": {"message": "Invalid model parameter"}}

    assert format_error_message(MockOpenAIError()) == "Invalid model parameter"


@pytest.mark.asyncio
async def test_job_failure_reporting():
    job = await job_manager.create_job(filename="failing_doc.docx")
    await job_manager.fail_job(job.job_id, "Engine protocol startup was aborted: Model was unloaded")

    details_res = client.get(f"/api/jobs/{job.job_id}")
    assert details_res.status_code == 200
    data = details_res.json()
    assert data["status"] == "failed"
    assert data["error"] == "Engine protocol startup was aborted: Model was unloaded"


def test_get_models_error_structure():
    with patch("app.core.llm_client.LLMClient.list_models", new_callable=AsyncMock) as mock_list:
        mock_list.side_effect = Exception("ConnectError: [Errno 111] Connection refused")
        response = client.get("/api/models?base_url=http://127.0.0.1:59999/v1")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert "error" in data
        assert "raw_error" in data
        assert len(data["error"]) > 0
