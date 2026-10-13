import asyncio
import hmac
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile

from app.config import settings
from app.services.gemini_service import AIUnavailableError, analyze_resume_fit, generate_jd_from_title, ocr_document
from app.services.limits import LimitExceeded, limiter
from app.services.matcher import EmbeddingUnavailableError, cosine_similarity_score, embed_job_description, embed_resume
from app.services.parser import IMAGE_MIME_TYPES, DocumentError, clean_text, detect_format, extract_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Resumes"])

# Inputs shorter than this are treated as a job title and expanded into a generic JD.
# The response flags this so the UI can show the generated text as AI-written.
SHORT_JD_THRESHOLD = 50
# Limit concurrent resume pipelines to keep memory and provider bursts low
CONCURRENCY_LIMIT = 4
_semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)


async def _read_text(file_bytes: bytes, file_format: str) -> dict:
    """Returns {"text", "method", "truncated"}. Raises DocumentError or AIUnavailableError."""
    raw_text = clean_text(await asyncio.to_thread(extract_text, file_bytes, file_format))
    if raw_text:
        return {"text": raw_text, "method": "text", "truncated": False}

    if file_format == "pdf" or file_format in IMAGE_MIME_TYPES:
        mime_type = "application/pdf" if file_format == "pdf" else IMAGE_MIME_TYPES[file_format]
        try:
            ocr = await ocr_document(file_bytes, mime_type)
        except AIUnavailableError:
            raise DocumentError(
                "This file has no text layer and text recognition (OCR) is temporarily unavailable."
            ) from None
        ocr_text = clean_text(ocr["text"])
        if ocr_text:
            return {"text": ocr_text, "method": "ocr", "truncated": ocr["truncated"]}

    raise DocumentError("No readable text was found in this document.")


async def process_single_resume(file: UploadFile, final_jd: str, jd_embedding: Optional[List[float]]) -> dict:
    """Parses, scores and analyses one resume. Failures are reported, never disguised as results."""
    filename = file.filename or "unnamed"
    async with _semaphore:
        try:
            file.file.seek(0, 2)
            file_size = file.file.tell()
            file.file.seek(0)
            if file_size > settings.max_file_size_bytes:
                raise DocumentError(f"File exceeds the {settings.MAX_FILE_SIZE_MB} MB limit.")

            file_bytes = await file.read()
            file_format = detect_format(file_bytes, filename)
            extraction = await _read_text(file_bytes, file_format)
            del file_bytes
            raw_text = extraction["text"]

            async def score() -> float:
                if jd_embedding is None:
                    raise EmbeddingUnavailableError("Similarity scoring is temporarily unavailable.")
                return cosine_similarity_score(await embed_resume(raw_text), jd_embedding)

            # Scoring and analysis are independent, so run them together.
            score_result, analysis_result = await asyncio.gather(
                score(), analyze_resume_fit(raw_text, final_jd), return_exceptions=True
            )

            warnings = []
            if extraction["method"] == "ocr":
                warnings.append("Text was read with AI text recognition (OCR) and may contain errors.")
            if extraction["truncated"]:
                warnings.append("Text recognition hit its output limit; later parts of the document may be missing.")

            if isinstance(score_result, EmbeddingUnavailableError):
                similarity_score = None
                warnings.append(str(score_result))
            elif isinstance(score_result, BaseException):
                raise score_result
            else:
                similarity_score = score_result

            if isinstance(analysis_result, AIUnavailableError):
                analysis = None
                warnings.append(str(analysis_result))
            elif isinstance(analysis_result, BaseException):
                raise analysis_result
            else:
                analysis = analysis_result
                if analysis.get("input_truncated"):
                    warnings.append("The resume was too long to analyse in full; the analysis covers only the first part.")

            return {
                "filename": filename,
                "status": "success" if similarity_score is not None and analysis is not None else "partial",
                "similarity_score": similarity_score,
                "analysis": analysis,
                "extraction_method": extraction["method"],
                "warnings": warnings,
                "raw_text": raw_text,
            }

        except DocumentError as e:
            return {"filename": filename, "status": "error", "error_message": str(e)}
        except Exception as e:
            logger.exception("unexpected error processing resume", extra={"error": type(e).__name__})
            return {"filename": filename, "status": "error", "error_message": "Unexpected error while processing this file."}


def _sort_key(result: dict):
    # Scored results first (highest first), then unscored ones, then errors.
    # Equal scores are ordered by filename so the same upload always gives the same order.
    if result["status"] == "error":
        return (2, 0.0, result["filename"])
    if result.get("similarity_score") is None:
        return (1, 0.0, result["filename"])
    return (0, -result["similarity_score"], result["filename"])


def _check_access_code(provided: Optional[str]) -> None:
    if settings.DEMO_ACCESS_CODE and not hmac.compare_digest(
        (provided or "").encode(), settings.DEMO_ACCESS_CODE.encode()
    ):
        raise HTTPException(status_code=401, detail="A valid demo access code is required.")


@router.post("/match")
async def match_resumes(
    request: Request,
    files: List[UploadFile] = File(...),
    job_description: str = Form(...),
    x_demo_access_code: Optional[str] = Header(default=None),
):
    """
    Accepts resume files and a job description (full text, or a short job title that is
    expanded by AI and flagged as such). Returns one result per file.

    `similarity_score` is the cosine similarity of the JD and resume embeddings on a 0-100
    scale. It is not a probability of fit and is `null` when it could not be computed.
    """
    _check_access_code(x_demo_access_code)

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    if len(files) > settings.MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Maximum of {settings.MAX_FILES} files allowed per request.")

    jd_input = job_description.strip()
    if not jd_input:
        raise HTTPException(status_code=400, detail="Job description cannot be empty.")
    if len(jd_input) > settings.MAX_JD_CHARS:
        raise HTTPException(status_code=400, detail=f"Job description must be under {settings.MAX_JD_CHARS} characters.")

    client = request.client.host if request.client else "unknown"
    try:
        limiter.check_and_reserve(client, len(files))
    except LimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e), headers={"Retry-After": str(e.retry_after)}) from None

    run_id = uuid.uuid4().hex[:12]
    logger.info("match request", extra={"run_id": run_id, "files": len(files), "jd_chars": len(jd_input)})

    is_expanded = False
    final_jd = jd_input
    if len(jd_input) < SHORT_JD_THRESHOLD:
        try:
            final_jd = await generate_jd_from_title(jd_input)
            is_expanded = True
        except AIUnavailableError:
            raise HTTPException(
                status_code=503,
                detail="Could not expand the short job title right now. Please paste a full job description instead.",
            ) from None

    # Embed the JD once. If it fails, every resume still gets parsed and analysed, but no scores.
    jd_embedding = None
    try:
        jd_embedding = await embed_job_description(final_jd)
    except EmbeddingUnavailableError:
        logger.warning("jd embedding unavailable", extra={"run_id": run_id})

    results = await asyncio.gather(*(process_single_resume(f, final_jd, jd_embedding) for f in files))
    results.sort(key=_sort_key)

    logger.info(
        "match complete",
        extra={"run_id": run_id, "statuses": [r["status"] for r in results], "scoring_available": jd_embedding is not None},
    )
    return {
        "run_id": run_id,
        "job_description_used": final_jd,
        "is_job_description_expanded": is_expanded,
        "scoring_available": jd_embedding is not None,
        "results": results,
    }
