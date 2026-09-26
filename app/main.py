import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router

# Configure centralized logging format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("documend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("DocuMend server initialized. Ready at http://127.0.0.1:8000")
    yield
    logger.info("DocuMend server shutting down.")


app = FastAPI(
    title="DocuMend",
    description="Privacy-preserving local DOCX grammar and spell checker powered by any OpenAI-compatible LLM runtime.",
    version="0.1.0",
    lifespan=lifespan,
)

# Enable CORS for local client-server flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(api_router)

# Mount static assets
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def serve_index():
    """Serve the single-page frontend application."""
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "DocuMend API is running. Place index.html in app/static."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
