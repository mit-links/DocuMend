"""Application entrypoint and FastAPI server configuration for DocuMend."""

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
import os
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn

from app.api.routes import router as api_router
from app.config import settings

# Configure centralized logging format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("documend")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan context manager."""
    logger.info("DocuMend backend ready to receive requests.")
    yield
    logger.info("DocuMend backend shutting down.")


app = FastAPI(
    title="DocuMend",
    description="Privacy-preserving local DOCX grammar and spell checker powered by any OpenAI-compatible LLM runtime.",
    version="0.1.0",
    lifespan=lifespan,
)

# Register API routes
app.include_router(api_router)

# Mount static assets
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def serve_index() -> Response:
    """Serves the single-page frontend application."""
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return Response(
        content='{"message": "DocuMend API is running. Place index.html in app/static."}',
        media_type="application/json",
    )


def main() -> None:
    """CLI entrypoint parsing arguments and starting Uvicorn server."""
    parser = argparse.ArgumentParser(
        description="DocuMend: Local DOCX Grammar & Spell Checker",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=settings.port,
        help="Port to bind the web server to (default: 8000)",
    )
    parser.add_argument(
        "--host",
        "-H",
        type=str,
        default=settings.host,
        help="Host address to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="Enable auto-reload for development",
    )

    args = parser.parse_args()

    if not (1 <= args.port <= 65535):
        parser.error(f"Port must be between 1 and 65535, got {args.port}")

    logger.info(f"Starting DocuMend on http://{args.host}:{args.port}")
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
