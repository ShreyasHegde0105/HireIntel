from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from resume_platform.ingestion.extractors import DocxExtractor, PdfExtractor, TextExtractor
from resume_platform.ingestion.models import DocumentIngestResponse, StoredDocument


class DocumentIngestionService:
    def __init__(self, storage_dir: Path) -> None:
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._extractors = {
            ".pdf": PdfExtractor(),
            ".docx": DocxExtractor(),
            ".txt": TextExtractor(),
        }

    def ingest_bytes(self, filename: str, content: bytes) -> DocumentIngestResponse:
        extension = Path(filename).suffix.lower()
        extractor = self._extractors.get(extension)
        if extractor is None:
            supported = ", ".join(sorted(self._extractors))
            raise ValueError(f"Unsupported file type '{extension or 'unknown'}'. Supported types: {supported}.")

        if not content:
            raise ValueError("Uploaded file is empty.")

        extracted_text = extractor.extract(content)
        document = self._persist_document(
            filename=filename,
            content_type=extension.lstrip("."),
            extracted_text=extracted_text,
        )
        return DocumentIngestResponse(
            document_id=document.document_id,
            filename=document.filename,
            content_type=document.content_type,
            character_count=document.character_count,
            storage_path=str(document.storage_path),
            created_at=document.created_at,
        )

    def _persist_document(self, filename: str, content_type: str, extracted_text: str) -> StoredDocument:
        document_id = uuid4().hex
        created_at = datetime.now(UTC)
        safe_name = _slugify_filename(filename)
        target_dir = self.storage_dir / document_id
        target_dir.mkdir(parents=True, exist_ok=False)

        payload = {
            "document_id": document_id,
            "filename": filename,
            "content_type": content_type,
            "character_count": len(extracted_text),
            "extracted_text": extracted_text,
            "created_at": created_at.isoformat(),
        }

        storage_path = target_dir / f"{safe_name}.json"
        storage_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        return StoredDocument(
            document_id=document_id,
            filename=filename,
            content_type=content_type,
            character_count=len(extracted_text),
            extracted_text=extracted_text,
            storage_path=storage_path,
            created_at=created_at,
        )


def _slugify_filename(filename: str) -> str:
    stem = Path(filename).stem.strip().lower() or "document"
    normalized = re.sub(r"[^a-z0-9]+", "-", stem)
    return normalized.strip("-") or "document"
