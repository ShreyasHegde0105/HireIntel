import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.logging_config import configure_logging
from app.routers import resume

logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
# Room for multipart overhead and the job description on top of the files themselves
BODY_OVERHEAD_BYTES = 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings.validate()  # Fail fast if critical settings (e.g. GEMINI_API_KEY) are missing
    logger.info(
        "starting",
        extra={
            "generation_models": settings.GENERATION_MODELS,
            "embedding_model": settings.EMBEDDING_MODEL,
            "access_code_required": bool(settings.DEMO_ACCESS_CODE),
        },
    )
    yield


app = FastAPI(
    title="HireIntel API",
    description="Resume review assistant: parses resumes, scores embedding similarity against a job "
    "description, and produces AI-written strengths and gaps. Advisory only.",
    version="1.1.0",
    lifespan=lifespan,
)

if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Demo-Access-Code"],
    )


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """Rejects oversized uploads before the body is read."""
    if request.method == "POST":
        max_bytes = settings.MAX_FILES * settings.max_file_size_bytes + BODY_OVERHEAD_BYTES
        length = request.headers.get("content-length")
        if length is None:
            return JSONResponse(status_code=411, content={"detail": "Content-Length header is required."})
        if not length.isdigit() or int(length) > max_bytes:
            return JSONResponse(status_code=413, content={"detail": "Upload is too large."})
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # Return one readable message instead of FastAPI's list of error objects.
    fields = ", ".join(str(err["loc"][-1]) for err in exc.errors())
    return JSONResponse(status_code=422, content={"detail": f"Missing or invalid fields: {fields}."})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("unhandled error", extra={"path": request.url.path, "error": type(exc).__name__})
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


app.include_router(resume.router)


@app.get("/health", tags=["Health"])
def health():
    """Liveness check. Does not call the AI provider, so it costs no quota."""
    return {
        "status": "ok",
        "ai_configured": bool(settings.GEMINI_API_KEY),
        "generation_models": settings.GENERATION_MODELS,
        "embedding_model": settings.EMBEDDING_MODEL,
    }


@app.get("/api/config", tags=["Health"])
def public_config():
    """Limits the frontend needs to validate input before uploading."""
    return {
        "max_files": settings.MAX_FILES,
        "max_file_size_mb": settings.MAX_FILE_SIZE_MB,
        "access_code_required": bool(settings.DEMO_ACCESS_CODE),
    }


# Serve the frontend from the same origin, so no CORS is needed in the default deployment.
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
