from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from resume_platform.ingestion.models import DocumentIngestResponse
from resume_platform.ingestion.service import DocumentIngestionService

router = APIRouter(prefix="/documents", tags=["documents"])


def get_ingestion_service() -> DocumentIngestionService:
    storage_dir = Path("data/raw")
    return DocumentIngestionService(storage_dir=storage_dir)


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/ingest",
    response_model=DocumentIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_document(
    file: UploadFile = File(...),
    service: DocumentIngestionService = Depends(get_ingestion_service),
) -> DocumentIngestResponse:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must include a filename.",
        )

    content = await file.read()
    try:
        return service.ingest_bytes(filename=file.filename, content=content)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
