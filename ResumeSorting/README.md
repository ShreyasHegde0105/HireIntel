# Resume Intelligence Platform

Python-based AI platform for semantic resume-job matching, built in 5 progressive stages.

Current implementation status: `Stage 1 complete`

## Project stages

| Stage | Name | Status |
|-------|------|--------|
| 1 | Document Reader | implemented |
| 2 | Information Extraction System | planned |
| 3 | AI Semantic Matching Engine | planned |
| 4 | Explainable Recruitment Intelligence | planned |
| 5 | Enterprise Document Intelligence Platform | planned |

## Architecture

```text
resume_platform/
|-- ingestion/       # Stage 1: PDF/DOCX/TXT parsing and persistence
|-- api/             # FastAPI entrypoints
`-- tests/
```

## Stack

- Runtime: Python 3.11+
- API: FastAPI
- PDF parsing: PyMuPDF, pdfplumber
- DOCX parsing: python-docx
- Validation: Pydantic

## Stage 1

Goal: ingest and extract raw text from uploaded resumes and job descriptions.

Implemented:
- Accepts `.pdf`, `.docx`, and `.txt` uploads
- Extracts plain text using PyMuPDF with a `pdfplumber` fallback for PDFs
- Extracts DOCX paragraph and table content using `python-docx`
- Persists raw extracted text as JSON for downstream stages
- Exposes a thin FastAPI endpoint for ingestion

Not included yet:
- OCR for scanned PDFs
- NLP field extraction
- Matching or scoring logic

## API

Health check:

```text
GET /documents/health
```

Ingest document:

```text
POST /documents/ingest
multipart/form-data
field: file
```

Example response:

```json
{
  "document_id": "4aa2d8e8d5c64dbdbd21f7d8087dcf5d",
  "filename": "sample_resume.pdf",
  "content_type": "pdf",
  "character_count": 4287,
  "storage_path": "data/raw/4aa2d8e8d5c64dbdbd21f7d8087dcf5d/sample-resume.json",
  "created_at": "2026-05-13T05:00:00+00:00"
}
```

Persisted payload shape:

```json
{
  "document_id": "4aa2d8e8d5c64dbdbd21f7d8087dcf5d",
  "filename": "sample_resume.pdf",
  "content_type": "pdf",
  "character_count": 4287,
  "extracted_text": "Raw extracted document text...",
  "created_at": "2026-05-13T05:00:00+00:00"
}
```

## Quick Start

Install dependencies:

```bash
pip install -e .[dev]
```

Run the API:

```bash
uvicorn resume_platform.api.main:app --reload
```

Test an upload:

```bash
curl -X POST "http://127.0.0.1:8000/documents/ingest" -F "file=@sample_resume.pdf"
```

Run tests:

```bash
pytest
```

## Code conventions

- Type-annotate all functions
- Use Pydantic models for API request and response schemas
- Keep FastAPI routers thin and business logic inside services
- Prefer explicit extraction failures over silent fallbacks
