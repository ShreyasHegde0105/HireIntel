import asyncio
import hmac
import json
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile

from app.config import settings
from app.services.gemini_service import AIUnavailableError, analyze_resume_fit, generate_jd_from_title, ocr_document
from app.services.limits import LimitExceeded, limiter
from app.services.matcher import EmbeddingUnavailableError, cosine_similarity_score, embed_job_description, embed_resume
from app.services.parser import IMAGE_MIME_TYPES, DocumentError, clean_text, detect_format, extract_document
from app.services.requirements import assess_resume, extract_requirements, requirement_sort_key, validate_requirements

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Resumes"])

# Inputs shorter than this are treated as a job title and expanded into a generic JD.
# The response flags this so the UI can show the generated text as AI-written.
SHORT_JD_THRESHOLD = 50
# Limit concurrent resume pipelines to keep memory and provider bursts low
CONCURRENCY_LIMIT = 4
_semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
# Hidden text returned to the recruiter, so the response stays small
MAX_HIDDEN_SNIPPETS = 5
MAX_HIDDEN_SNIPPET_CHARS = 300


async def _read_text(file_bytes: bytes, file_format: str) -> dict:
    """Returns {"text", "method", "truncated", "hidden"}. Raises DocumentError or AIUnavailableError."""
    document = await asyncio.to_thread(extract_document, file_bytes, file_format)
    raw_text = clean_text(document.text)
    hidden = [h for h in (clean_text(h) for h in document.hidden) if h]
    if raw_text:
        return {"text": raw_text, "method": "text", "truncated": False, "hidden": hidden}

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
            # OCR reads what is visible on the page, so hidden text found earlier stays out.
            return {"text": ocr_text, "method": "ocr", "truncated": ocr["truncated"], "hidden": hidden}

    raise DocumentError("No readable text was found in this document.")


async def process_single_resume(
    file: UploadFile,
    final_jd: str,
    jd_embedding: Optional[List[float]],
    requirements: Optional[List[dict]] = None,
) -> dict:
    """Parses, scores and analyses one resume. Failures are reported, never disguised as results.

    With confirmed requirements, the AI step is a per-requirement assessment with verified
    quotes ("assessment"); otherwise it is the free-form analysis ("analysis").
    """
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

            ai_step = assess_resume(raw_text, requirements) if requirements else analyze_resume_fit(raw_text, final_jd)
            # Scoring and analysis are independent, so run them together.
            score_result, analysis_result = await asyncio.gather(score(), ai_step, return_exceptions=True)

            warnings = []
            if extraction["method"] == "ocr":
                warnings.append("Text was read with AI text recognition (OCR) and may contain errors.")
            if extraction["truncated"]:
                warnings.append("Text recognition hit its output limit; later parts of the document may be missing.")
            hidden = extraction["hidden"]
            if hidden:
                warnings.append(
                    "This file contains text a reader cannot see (hidden, white, tiny or off-page). It was left out "
                    "of the analysis. Hidden text is sometimes used to game screening tools; check the original file."
                )
                logger.info("hidden text left out", extra={"snippets": len(hidden), "chars": sum(len(h) for h in hidden)})

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
                if analysis.get("manipulation_detected"):
                    warnings.append("This resume contains text aimed at AI screening tools. It was ignored, but review the resume manually.")

            return {
                "filename": filename,
                "status": "success" if similarity_score is not None and analysis is not None else "partial",
                "similarity_score": similarity_score,
                ("assessment" if requirements else "analysis"): analysis,
                "extraction_method": extraction["method"],
                "warnings": warnings,
                "hidden_text": [h[:MAX_HIDDEN_SNIPPET_CHARS] for h in hidden[:MAX_HIDDEN_SNIPPETS]],
                "hidden_text_count": len(hidden),
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


def _validated_jd(job_description: str) -> str:
    jd_input = job_description.strip()
    if not jd_input:
        raise HTTPException(status_code=400, detail="Job description cannot be empty.")
    if len(jd_input) > settings.MAX_JD_CHARS:
        raise HTTPException(status_code=400, detail=f"Job description must be under {settings.MAX_JD_CHARS} characters.")
    return jd_input


def _reserve(request: Request, units: int) -> None:
    client = request.client.host if request.client else "unknown"
    try:
        limiter.check_and_reserve(client, units)
    except LimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e), headers={"Retry-After": str(e.retry_after)}) from None


@router.post("/requirements")
async def propose_requirements(
    request: Request,
    job_description: str = Form(...),
    x_demo_access_code: Optional[str] = Header(default=None),
):
    """
    Proposes a requirement checklist from a job description for the recruiter to edit and
    confirm. Conditions a resume cannot show (citizenship, documents, shift availability...)
    are returned separately in `not_assessable`.
    """
    _check_access_code(x_demo_access_code)
    jd_input = _validated_jd(job_description)
    _reserve(request, 1)
    try:
        return await extract_requirements(jd_input)
    except AIUnavailableError:
        raise HTTPException(status_code=503, detail="Could not extract requirements right now. Please try again shortly.") from None


@router.post("/match")
async def match_resumes(
    request: Request,
    files: List[UploadFile] = File(...),
    job_description: str = Form(...),
    requirements: Optional[str] = Form(default=None),
    x_demo_access_code: Optional[str] = Header(default=None),
):
    """
    Accepts resume files and a job description (full text, or a short job title that is
    expanded by AI and flagged as such). Returns one result per file.

    Optional `requirements` is a JSON list of recruiter-confirmed requirements
    (`[{"text": ..., "importance": "mandatory" | "preferred"}]`). When given, each resume gets
    a per-requirement assessment with verified quotes and an evidence band, and results are
    ordered by band. No band rejects anyone.

    `similarity_score` is the cosine similarity of the JD and resume embeddings on a 0-100
    scale. It is not a probability of fit and is `null` when it could not be computed.
    """
    _check_access_code(x_demo_access_code)

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    if len(files) > settings.MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Maximum of {settings.MAX_FILES} files allowed per request.")

    jd_input = _validated_jd(job_description)

    confirmed = None
    if requirements is not None and requirements.strip():
        try:
            confirmed = validate_requirements(json.loads(requirements))
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Requirements must be valid JSON.") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    _reserve(request, len(files))

    run_id = uuid.uuid4().hex[:12]
    logger.info(
        "match request",
        extra={"run_id": run_id, "files": len(files), "jd_chars": len(jd_input), "requirements": len(confirmed or [])},
    )

    is_expanded = False
    final_jd = jd_input
    if confirmed and len(jd_input) < SHORT_JD_THRESHOLD:
        # The confirmed requirements describe the job, so there is no need to invent a full JD.
        final_jd = "\n".join([jd_input] + [r["text"] for r in confirmed])
    elif len(jd_input) < SHORT_JD_THRESHOLD:
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

    results = await asyncio.gather(*(process_single_resume(f, final_jd, jd_embedding, confirmed) for f in files))
    results.sort(key=requirement_sort_key if confirmed else _sort_key)

    logger.info(
        "match complete",
        extra={"run_id": run_id, "statuses": [r["status"] for r in results], "scoring_available": jd_embedding is not None},
    )
    return {
        "run_id": run_id,
        "mode": "requirements" if confirmed else "similarity",
        "requirements": confirmed,
        "job_description_used": final_jd,
        "is_job_description_expanded": is_expanded,
        "scoring_available": jd_embedding is not None,
        "results": results,
    }
