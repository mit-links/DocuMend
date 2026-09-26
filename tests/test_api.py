import io
import pytest
from fastapi.testclient import TestClient
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
    response = client.get("/api/models?base_url=http://127.0.0.1:1234/v1")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("connected", "error")
    if data["status"] == "connected":
        assert isinstance(data["models"], list)
        assert len(data["models"]) > 0


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

    files = {"file": ("sample.docx", io.BytesIO(file_bytes), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    data = {
        "base_url": "http://127.0.0.1:1234/v1",
        "api_key": "not-needed",
        "model": "qwen/qwen3.5-9b",
        "concurrency": "4",
    }
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

    # Test concurrency = 0 (rejected with 400)
    files = {"file": ("sample.docx", io.BytesIO(file_bytes), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    data = {"concurrency": "0"}
    response = client.post("/api/process", files=files, data=data)
    assert response.status_code == 400
    assert "positive integer" in response.json()["detail"]

    # Test negative concurrency = -5 (rejected with 400)
    files = {"file": ("sample.docx", io.BytesIO(file_bytes), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    data = {"concurrency": "-5"}
    response = client.post("/api/process", files=files, data=data)
    assert response.status_code == 400
    assert "positive integer" in response.json()["detail"]

    # Test non-integer concurrency = "abc" (FastAPI rejects with 422)
    files = {"file": ("sample.docx", io.BytesIO(file_bytes), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    data = {"concurrency": "abc"}
    response = client.post("/api/process", files=files, data=data)
    assert response.status_code == 422


def test_eject_models_endpoint():
    # Eject endpoint is best-effort and always returns 200 with status ok or ignored
    response = client.post(
        "/api/models/eject",
        data={
            "base_url": "http://127.0.0.1:1234/v1",
            "active_model": "qwen/qwen3.5-9b",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "ignored")
    assert isinstance(data["ejected"], list)


def test_cancel_nonexistent_job():
    response = client.post("/api/jobs/nonexistent123/cancel")
    assert response.status_code == 404


def test_cancel_active_job(tmp_path):
    sample_file = tmp_path / "sample.docx"
    generate_sample_docx(str(sample_file))

    with open(sample_file, "rb") as f:
        file_bytes = f.read()

    files = {"file": ("sample.docx", io.BytesIO(file_bytes), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    res = client.post("/api/process", files=files, data={"concurrency": "1"})
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    # Cancel the job
    cancel_res = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancel_res.status_code == 200
    cancel_data = cancel_res.json()
    assert cancel_data["job_id"] == job_id
    assert cancel_data["status"] == "cancelled"

    # Attempting to download cancelled job must return 400
    dl_res = client.get(f"/api/jobs/{job_id}/download")
    assert dl_res.status_code == 400
    assert "cancelled" in dl_res.json()["detail"].lower()


def test_upload_file_cleanup_and_no_lingering_temp_files(tmp_path):
    sample_file = tmp_path / "sample.docx"
    generate_sample_docx(str(sample_file))

    with open(sample_file, "rb") as f:
        file_bytes = f.read()

    # Upload valid docx
    files = {"file": ("sample.docx", io.BytesIO(file_bytes), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    res = client.post("/api/process", files=files, data={"concurrency": "1"})
    assert res.status_code == 200

    # Upload invalid docx (error branch)
    files_err = {"file": ("error.txt", io.BytesIO(b"not a docx"), "text/plain")}
    res_err = client.post("/api/process", files=files_err)
    assert res_err.status_code == 400


def test_get_job_details(tmp_path):
    sample_file = tmp_path / "sample.docx"
    generate_sample_docx(str(sample_file))

    with open(sample_file, "rb") as f:
        file_bytes = f.read()

    files = {"file": ("sample.docx", io.BytesIO(file_bytes), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    res = client.post("/api/process", files=files, data={"concurrency": "1"})
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    # Query details endpoint
    details_res = client.get(f"/api/jobs/{job_id}")
    assert details_res.status_code == 200
    data = details_res.json()
    assert data["job_id"] == job_id
    assert "status" in data
    assert "percent" in data

    # Non-existent job
    missing_res = client.get("/api/jobs/missing999")
    assert missing_res.status_code == 404


def test_format_error_message():
    from app.api.routes import format_error_message

    class MockOpenAIError(Exception):
        def __init__(self, body):
            self.body = body

    # OpenAI-style nested dict error
    err1 = MockOpenAIError({"error": {"message": "Engine protocol startup was aborted: Model was unloaded"}})
    assert format_error_message(err1) == "Engine protocol startup was aborted: Model was unloaded"

    # OpenAI-style string error
    err2 = MockOpenAIError({"error": "Model unloaded"})
    assert format_error_message(err2) == "Model unloaded"

    # LLM Server Error prefix stripping
    err3 = RuntimeError("LLM Server Error: Request timed out")
    assert format_error_message(err3) == "Request timed out"

    # Google Gemini style list body error
    err5 = MockOpenAIError([{"error": {"code": 400, "message": "Please pass a valid API key", "status": "INVALID_ARGUMENT"}}])
    assert format_error_message(err5) == "Please pass a valid API key"

    # String with raw dict / json representation
    err6 = Exception("Error code: 400 - [{'error': {'code': 400, 'message': 'Please pass a valid API key', 'status': 'INVALID_ARGUMENT'}}]")
    assert format_error_message(err6) == "Please pass a valid API key"

    # Connection refused
    err7 = Exception("httpx.ConnectError: [Errno 111] Connection refused")
    assert "Connection refused" in format_error_message(err7)


@pytest.mark.asyncio
async def test_job_failure_reporting():
    from app.api.job_manager import job_manager

    job = await job_manager.create_job(filename="failing_doc.docx")
    await job_manager.fail_job(job.job_id, "Engine protocol startup was aborted: Model was unloaded")

    details_res = client.get(f"/api/jobs/{job.job_id}")
    assert details_res.status_code == 200
    data = details_res.json()
    assert data["status"] == "failed"
    assert data["error"] == "Engine protocol startup was aborted: Model was unloaded"


def test_get_models_error_structure():
    # Query an invalid/unreachable port
    response = client.get("/api/models?base_url=http://127.0.0.1:59999/v1")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "error" in data
    assert "raw_error" in data
    assert len(data["error"]) > 0






