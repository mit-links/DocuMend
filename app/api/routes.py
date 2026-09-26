"""HTTP routes and Server-Sent Events (SSE) endpoints for DocuMend."""

import asyncio
import io
import json
import logging
import re
import time
from typing import Any, Optional
import urllib.parse
import zipfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.api.job_manager import job_manager
from app.config import settings
from app.core.docx_processor import DocxProcessor
from app.core.llm_client import LLMClient

logger = logging.getLogger("documend.api")

router = APIRouter(prefix="/api")


def format_error_message(err: Exception) -> str:
    """Formats exceptions into clean, human-readable error messages for the user.

    Args:
        err: The exception to format.

    Returns:
        A concise user-facing error message.
    """
    target = getattr(err, "__cause__", None) or err

    # Check for OpenAI APIError body structure
    if hasattr(target, "body"):
        body = target.body
        if isinstance(body, list) and len(body) > 0:
            body = body[0]
        if isinstance(body, dict):
            err_obj = body.get("error")
            if isinstance(err_obj, dict) and "message" in err_obj:
                return str(err_obj["message"]).strip()
            if isinstance(err_obj, str):
                return err_obj.strip()

    if hasattr(target, "message") and target.message:
        return str(target.message).strip()

    err_str = str(target)
    if "LLM Server Error: " in err_str:
        err_str = err_str.split("LLM Server Error: ", 1)[-1].strip()

    # Match JSON error messages without truncating on embedded quotes
    match = re.search(r"['\"]message['\"]\s*:\s*(['\"])(.*?)\1(?:,|\s*\}|$)", err_str, re.DOTALL)
    if match:
        return match.group(2).strip()

    if "Connection refused" in err_str or "ConnectError" in err_str:
        return "Connection refused: server is not reachable."

    if "401" in err_str and ("unauthorized" in err_str.lower() or "api key" in err_str.lower()):
        return "Unauthorized: Invalid API key."

    return err_str


@router.get("/models")
async def get_available_models(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """Queries available models from any OpenAI-compatible server.

    Args:
        base_url: Optional base URL of the LLM server.
        api_key: Optional API key for remote providers.

    Returns:
        Dictionary with connection status, models list, and error info if any.
    """
    target_url = base_url or settings.default_base_url
    target_key = api_key or settings.default_api_key

    logger.info(f"Querying models from LLM server at {target_url}...")
    client = LLMClient(base_url=target_url, api_key=target_key)
    try:
        models = await client.list_models()
        logger.info(f"Connected to {target_url}. Found {len(models)} model(s): {models}")
        return {
            "status": "connected",
            "base_url": client.base_url,
            "models": models,
        }
    except Exception as e:
        logger.warning(f"Failed to query models from {target_url}: {e}")
        main_message = format_error_message(e)
        return {
            "status": "error",
            "base_url": target_url,
            "models": [],
            "error": main_message,
            "raw_error": str(e),
        }
    finally:
        await client.close()


@router.post("/models/eject")
async def eject_inactive_models_endpoint(
    base_url: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
) -> dict[str, Any]:
    """Attempts to eject/unload any inactive models on the server to free VRAM.

    Args:
        base_url: Optional base URL.
        api_key: Optional API key.

    Returns:
        Status and list of unloaded models.
    """
    target_url = base_url or settings.default_base_url
    target_key = api_key or settings.default_api_key

    client = LLMClient(base_url=target_url, api_key=target_key)
    try:
        ejected = await client.eject_inactive_models()
        return {
            "status": "ok",
            "ejected": ejected,
        }
    except Exception as e:
        logger.debug(f"Manual eject endpoint call ignored error: {e}")
        return {
            "status": "ignored",
            "ejected": [],
            "error": str(e),
        }
    finally:
        await client.close()


async def _run_document_job(
    job_id: str,
    file_bytes: bytes,
    base_url: Optional[str],
    api_key: Optional[str],
    model: Optional[str],
    concurrency: Optional[int],
) -> None:
    """Background task executing the document processing pipeline.

    Args:
        job_id: Unique job identifier.
        file_bytes: Source .docx binary content.
        base_url: Base URL of LLM server.
        api_key: API key.
        model: Model name.
        concurrency: Concurrency limit.
    """
    start_time = time.time()
    effective_concurrency = concurrency or settings.concurrency_limit
    logger.info(
        f"[Job {job_id}] Processing pipeline started. "
        f"File size: {len(file_bytes)/1024:.1f} KB, Concurrency: {effective_concurrency}, Model: '{model or 'auto'}'"
    )

    client = LLMClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
    )

    try:
        # Best-effort attempt to eject inactive models to free VRAM
        try:
            ejected = await client.eject_inactive_models()
            if ejected:
                logger.info(
                    f"[Job {job_id}] Ejected {len(ejected)} inactive model(s) to free VRAM: {ejected}"
                )
        except Exception as e:
            logger.debug(f"[Job {job_id}] Model ejection skipped or unsupported: {e}")

        processor = DocxProcessor(
            llm_client=client,
            concurrency_limit=effective_concurrency,
        )

        progress_tasks: set[asyncio.Task] = set()

        def on_progress(processed: int, total: int, snippet: str, is_complete: bool = False) -> None:
            percent = int((processed / total) * 100) if total > 0 else 100
            logger.info(f"[Job {job_id}] Progress [{processed}/{total}] ({percent}%): '{snippet}'")
            t = asyncio.create_task(
                job_manager.update_progress(
                    job_id=job_id,
                    processed=processed,
                    total=total,
                    snippet=snippet,
                )
            )
            progress_tasks.add(t)
            t.add_done_callback(progress_tasks.discard)

        job = await job_manager.get_job(job_id)

        try:
            if job and job.is_cancelled:
                logger.info(f"[Job {job_id}] Processing aborted before start because job was cancelled.")
                return

            corrected_bytes, stats = await processor.process_document(
                docx_bytes=file_bytes,
                model_override=model,
                progress_callback=on_progress,
                cancel_check=lambda: (job.is_cancelled if job else False),
            )

            if job and job.is_cancelled:
                logger.info(f"[Job {job_id}] Processing halted because job was cancelled.")
                return

            # BUG-02 Fix: Await any pending progress update tasks before marking complete
            if progress_tasks:
                await asyncio.gather(*list(progress_tasks), return_exceptions=True)

            duration = time.time() - start_time
            logger.info(
                f"[Job {job_id}] Document successfully corrected in {duration:.2f}s "
                f"(output: {len(corrected_bytes)/1024:.1f} KB, speed: {stats.get('words_per_second')} words/s"
                + (f", {stats.get('tokens_per_second')} tok/s" if stats.get("tokens_per_second") else "")
                + ")."
            )
            await job_manager.complete_job(job_id, corrected_bytes, stats=stats)
        except asyncio.CancelledError:
            logger.info(f"[Job {job_id}] Processing task was cancelled.")
            if progress_tasks:
                await asyncio.gather(*list(progress_tasks), return_exceptions=True)
            if job and not job.is_cancelled:
                await job_manager.cancel_job(job_id)
        except Exception as e:
            duration = time.time() - start_time
            logger.exception(f"[Job {job_id}] Processing failed after {duration:.2f}s: {e}")
            if progress_tasks:
                await asyncio.gather(*list(progress_tasks), return_exceptions=True)
            error_msg = format_error_message(e)
            await job_manager.fail_job(job_id, error_msg)
    finally:
        # BUG-13 Fix: Close HTTP client and release connection pool
        await client.close()


@router.post("/process")
async def process_document(
    file: UploadFile = File(...),
    base_url: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    concurrency: Optional[int] = Form(None),
) -> dict[str, Any]:
    """Uploads a .docx file and initiates background spelling and grammar processing.

    Args:
        file: Uploaded .docx file.
        base_url: Optional base URL of LLM server.
        api_key: Optional API key.
        model: Optional model name.
        concurrency: Optional concurrency limit.

    Returns:
        Job registration response with stream URL.
    """
    try:
        filename = file.filename or ""
        if not filename.lower().endswith(".docx"):
            logger.warning(f"Rejected non-docx file upload: '{filename}'")
            raise HTTPException(
                status_code=400,
                detail="Invalid file type. Only Microsoft Word (.docx) documents are supported.",
            )

        content = await file.read()
        if len(content) == 0:
            logger.warning(f"Rejected empty file upload: '{filename}'")
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")

        # BUG-15 Fix: Validate that uploaded content is a valid zip archive
        if not zipfile.is_zipfile(io.BytesIO(content)):
            logger.warning(f"Rejected corrupt/non-zip .docx upload: '{filename}'")
            raise HTTPException(
                status_code=400,
                detail="Invalid document structure. The uploaded file is not a valid .docx archive.",
            )

        if concurrency is not None and concurrency < 1:
            logger.warning(f"Rejected invalid concurrency: {concurrency}")
            raise HTTPException(
                status_code=400,
                detail="Concurrency must be a positive integer greater than or equal to 1.",
            )
    finally:
        await file.close()

    job = await job_manager.create_job(filename=filename)
    logger.info(
        f"[Job {job.job_id}] New document uploaded: '{filename}' ({len(content)/1024:.1f} KB). "
        f"Server: {base_url or settings.default_base_url}, Model: '{model or 'auto'}', Concurrency: {concurrency or settings.concurrency_limit}"
    )

    task = asyncio.create_task(
        _run_document_job(
            job_id=job.job_id,
            file_bytes=content,
            base_url=base_url,
            api_key=api_key,
            model=model,
            concurrency=concurrency,
        )
    )
    job.task = task

    return {
        "job_id": job.job_id,
        "filename": job.filename,
        "status": "pending",
        "stream_url": f"/api/jobs/{job.job_id}/stream",
    }


@router.get("/jobs/{job_id}")
async def get_job_details(job_id: str) -> dict[str, Any]:
    """Retrieves current details and performance statistics for a specific job."""
    job = await job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    res = job.to_summary_dict()
    res["download_url"] = (
        f"/api/jobs/{job.job_id}/download" if job.status == "completed" else None
    )
    return res


@router.post("/jobs/{job_id}/cancel")
async def cancel_job_endpoint(job_id: str) -> dict[str, Any]:
    """Cancels an ongoing document processing job."""
    job = await job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    success = await job_manager.cancel_job(job_id)
    logger.info(f"[Job {job_id}] Cancellation requested by user. Result: {success}")
    return {
        "job_id": job_id,
        "status": job.status,
        "success": success,
    }


@router.get("/jobs/{job_id}/stream")
async def stream_job_progress(job_id: str) -> StreamingResponse:
    """Server-Sent Events (SSE) endpoint streaming real-time progress for a job."""
    job = await job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    async def event_generator():
        queue = job.subscribe()
        try:
            # Emit current snapshot immediately
            yield f"data: {json.dumps(job.to_event_dict())}\n\n"
            if job.status in ("completed", "failed", "cancelled"):
                return

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("status") in ("completed", "failed", "cancelled"):
                        break
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                except asyncio.CancelledError:
                    break
        finally:
            job.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/jobs/{job_id}/download")
async def download_processed_document(job_id: str) -> Response:
    """Downloads the corrected .docx file."""
    job = await job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    if job.status == "cancelled":
        raise HTTPException(status_code=400, detail="Document processing was cancelled.")

    if job.status != "completed" or not job.result_bytes:
        raise HTTPException(status_code=400, detail="Document processing is not yet completed.")

    download_filename = f"corrected_{job.filename}"
    safe_filename = urllib.parse.quote(download_filename)
    logger.info(
        f"[Job {job_id}] User downloaded '{download_filename}' ({len(job.result_bytes)/1024:.1f} KB)."
    )
    return Response(
        content=job.result_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=\"{safe_filename}\"; filename*=UTF-8''{safe_filename}",
            "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    )
