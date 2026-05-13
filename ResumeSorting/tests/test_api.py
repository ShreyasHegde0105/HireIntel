from pathlib import Path

from fastapi.testclient import TestClient

from resume_platform.api.main import create_app
from resume_platform.api.routes.documents import get_ingestion_service
from resume_platform.ingestion.service import DocumentIngestionService


def test_ingest_endpoint_returns_created(tmp_path: Path) -> None:
    app = create_app()
    app.dependency_overrides[get_ingestion_service] = lambda: DocumentIngestionService(storage_dir=tmp_path)
    client = TestClient(app)

    response = client.post(
        "/documents/ingest",
        files={"file": ("resume.txt", b"Sam Taylor\nML Engineer", "text/plain")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["filename"] == "resume.txt"
    assert payload["content_type"] == "txt"


def test_ingest_endpoint_rejects_missing_filename(tmp_path: Path) -> None:
    app = create_app()
    app.dependency_overrides[get_ingestion_service] = lambda: DocumentIngestionService(storage_dir=tmp_path)
    client = TestClient(app)

    response = client.post(
        "/documents/ingest",
        files={"file": ("", b"abc", "text/plain")},
    )

    assert response.status_code == 400
