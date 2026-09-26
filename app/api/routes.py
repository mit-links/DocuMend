import asyncio
import json
import logging
import time
from typing import Optional
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.api.job_manager import job_manager
from app.config import settings
from app.core.docx_processor import DocxProcessor
from app.core.llm_client import LLMClient

logger = logging.getLogger("documend.api")

router = APIRouter(prefix="/api")


@router.get("/models")
async def get_available_models(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
):
    """Query available models from any OpenAI-compatible server."""
    target_url = base_url or settings.default_base_url
    target_key = api_key or settings.default_api_key

    logger.info(f"Querying models from LLM server at {target_url}...")
    try:
        client = LLMClient(base_url=target_url, api_key=target_key)
        models = await client.list_models()
        logger.info(f"Connected to {target_url}. Found {len(models)} model(s): {models}")
        return {
            "status": "connected",
            "base_url": client.base_url,
            "models": models,
        }
    except Exception as e:
        logger.warning(f"Failed to query models from {target_url}: {e}")
        return {
            "status": "error",
            "base_url": target_url,
            "models": [],
            "error": str(e),
        }


@router.post("/models/eject")
async def eject_inactive_models_endpoint(
    base_url: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    active_model: Optional[str] = Form(None),
):
    """Attempt to eject/unload any inactive models on the server to free VRAM."""
    target_url = base_url or settings.default_base_url
    target_key = api_key or settings.default_api_key

    client = LLMClient(base_url=target_url, api_key=target_key)
    try:
        ejected = await client.eject_inactive_models(active_model=active_model)
        return {
            "status": "ok",
            "active_model": active_model,
            "ejected": ejected,
        }
    except Exception as e:
        logger.debug(f"Manual eject endpoint call ignored error: {e}")
        return {
            "status": "ignored",
            "active_model": active_model,
            "ejected": [],
            "error": str(e),
        }


async def _run_document_job(
    job_id: str,
    file_bytes: bytes,
    base_url: Optional[str],
    api_key: Optional[str],
    model: Optional[str],
    concurrency: Optional[int],
):
    """Background task executing the document processing pipeline."""
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

    # Attempt to eject inactive models to free VRAM for the active model (best-effort)
    try:
        ejected = await client.eject_inactive_models(active_model=model)
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

    def on_progress(processed: int, total: int, snippet: str, is_complete: bool = False):
        percent = int((processed / total) * 100) if total > 0 else 100
        logger.info(f"[Job {job_id}] Progress [{processed}/{total}] ({percent}%): '{snippet}'")
        asyncio.create_task(
            job_manager.update_progress(
                job_id=job_id,
                processed=processed,
                total=total,
                snippet=snippet,
            )
        )

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
        if job and not job.is_cancelled:
            await job_manager.cancel_job(job_id)
    except Exception as e:
        duration = time.time() - start_time
        logger.exception(f"[Job {job_id}] Processing failed after {duration:.2f}s: {e}")
        error_msg = format_error_message(e)
        await job_manager.fail_job(job_id, error_msg)


def format_error_message(err: Exception) -> str:
    """Format exceptions into clean, human-readable error messages for the user."""
    # Check if OpenAI APIError / BadRequestError with JSON body
    if hasattr(err, "body") and isinstance(err.body, dict):
        err_obj = err.body.get("error")
        if isinstance(err_obj, dict) and "message" in err_obj:
            return err_obj["message"]
        if isinstance(err_obj, str):
            return err_obj

    if hasattr(err, "message") and err.message:
        return str(err.message)

    err_str = str(err)
    if "LLM Server Error: " in err_str:
        err_str = err_str.split("LLM Server Error: ", 1)[-1].strip()
    return err_str


@router.post("/process")
async def process_document(
    file: UploadFile = File(...),
    base_url: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    concurrency: Optional[int] = Form(None),
):
    """Upload a .docx file and initiate background spelling & grammar processing."""
    try:
        if not file.filename.lower().endswith(".docx"):
            logger.warning(f"Rejected non-docx file upload: '{file.filename}'")
            raise HTTPException(
                status_code=400,
                detail="Invalid file type. Only Microsoft Word (.docx) documents are supported.",
            )

        content = await file.read()
        if len(content) == 0:
            logger.warning(f"Rejected empty file upload: '{file.filename}'")
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")

        if concurrency is not None and concurrency < 1:
            logger.warning(f"Rejected invalid concurrency: {concurrency}")
            raise HTTPException(
                status_code=400,
                detail="Concurrency must be a positive integer greater than or equal to 1.",
            )
    finally:
        # Guarantee zero disk footprint:
        # Starlette's SpooledTemporaryFile spills to disk in OS temp directory if > 1MB.
        # Calling close() immediately deletes any spooled temporary file on disk.
        await file.close()

    job = await job_manager.create_job(filename=file.filename)
    logger.info(
        f"[Job {job.job_id}] New document uploaded: '{file.filename}' ({len(content)/1024:.1f} KB). "
        f"Server: {base_url or settings.default_base_url}, Model: '{model or 'auto'}', Concurrency: {concurrency or settings.concurrency_limit}"
    )

    # Launch background processing pipeline and attach task to job
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
async def get_job_details(job_id: str):
    """Retrieve current details and performance statistics for a specific job."""
    job = await job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {
        "job_id": job.job_id,
        "filename": job.filename,
        "status": job.status,
        "processed": job.processed_items,
        "total": job.total_items,
        "percent": job.progress_percent,
        "snippet": job.current_snippet,
        "stats": job.stats,
        "error": job.error_message,
        "download_url": f"/api/jobs/{job.job_id}/download" if job.status == "completed" else None,
    }


@router.post("/jobs/{job_id}/cancel")
async def cancel_job_endpoint(job_id: str):
    """Cancel an ongoing document processing job."""
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
async def stream_job_progress(job_id: str):
    """Server-Sent Events (SSE) endpoint streaming real-time progress for a job."""
    job = await job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    async def event_generator():
        # Emit initial state immediately
        initial_data = {
            "job_id": job.job_id,
            "status": job.status,
            "processed": job.processed_items,
            "total": job.total_items,
            "percent": job.progress_percent,
            "snippet": job.current_snippet,
        }
        if job.status == "completed":
            initial_data["download_url"] = f"/api/jobs/{job.job_id}/download"
            if job.stats:
                initial_data["stats"] = job.stats
        elif job.status == "failed":
            initial_data["error"] = job.error_message
        yield f"data: {json.dumps(initial_data)}\n\n"

        if job.status in ("completed", "failed", "cancelled"):
            return

        while True:
            try:
                # Wait for next event with a periodic heartbeat
                event = await asyncio.wait_for(job.events.get(), timeout=15.0)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("status") in ("completed", "failed", "cancelled"):
                    break
            except asyncio.TimeoutError:
                # Send SSE comment to keep connection alive
                yield ": heartbeat\n\n"
            except asyncio.CancelledError:
                break

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
async def download_processed_document(job_id: str):
    """Download the corrected .docx file."""
    job = await job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    if job.status == "cancelled":
        raise HTTPException(status_code=400, detail="Document processing was cancelled.")

    if job.status != "completed" or not job.result_bytes:
        raise HTTPException(status_code=400, detail="Document processing is not yet completed.")

    download_filename = f"corrected_{job.filename}"
    logger.info(f"[Job {job_id}] User downloaded '{download_filename}' ({len(job.result_bytes)/1024:.1f} KB).")
    return Response(
        content=job.result_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{download_filename}"',
            "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    )
