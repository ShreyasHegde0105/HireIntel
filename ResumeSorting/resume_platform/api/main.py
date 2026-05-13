from fastapi import FastAPI

from resume_platform.api.routes.documents import router as documents_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Resume Intelligence Platform",
        version="0.1.0",
        description="Stage 1 document reader API for resume and job description ingestion.",
    )
    app.include_router(documents_router)
    return app


app = create_app()
