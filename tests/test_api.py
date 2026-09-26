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

