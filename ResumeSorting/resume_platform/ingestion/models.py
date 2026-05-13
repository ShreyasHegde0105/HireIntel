from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class StoredDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    filename: str
    content_type: str
    character_count: int = Field(ge=0)
    extracted_text: str
    storage_path: Path
    created_at: datetime


class DocumentIngestResponse(BaseModel):
    document_id: str
    filename: str
    content_type: str
    character_count: int = Field(ge=0)
    storage_path: str
    created_at: datetime
