from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import List
import asyncio
import gc
from app.services.parser import extract_text
from app.services.matcher import calculate_similarity, get_embedding
from app.services.gemini_service import analyze_resume_fit, generate_jd_from_title, ocr_pdf_fallback, ocr_document_fallback

router = APIRouter(prefix="/api", tags=["Resumes"])

MAX_FILES = 20
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
# Limit concurrency to 4 simultaneous tasks to keep RAM footprint low (<500-700MB) while maintaining high speed
CONCURRENCY_LIMIT = 4
_semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

async def process_single_resume(file: UploadFile, final_jd: str, jd_embedding) -> dict:
    """
    Parses, embed-matches, and requests AI diagnostics for a single resume in-memory.
    Guarded by semaphore to ensure strictly controlled peak memory usage.
    """
    async with _semaphore:
        try:
            # Check file size before loading full contents
            file.file.seek(0, 2)
            file_size = file.file.tell()
            file.file.seek(0)
            
            if file_size > MAX_FILE_SIZE:
                raise ValueError(f"File exceeds the 5MB limit ({round(file_size / (1024 * 1024), 2)}MB uploaded).")

            # Read file stream directly into memory bytes
            file_bytes = await file.read()
            
            # Extract plain text (offloaded to thread with fast C++ pypdfium2 / python-docx)
            raw_text = await asyncio.to_thread(extract_text, file_bytes, file.filename)
            
            # If no text was extracted directly, attempt AI OCR fallback
            if not raw_text.strip():
                ext = file.filename.lower().split('.')[-1]
                if ext == 'pdf':
                    try:
                        raw_text = await ocr_pdf_fallback(file_bytes)
                    except Exception as ocr_err:
                        raise ValueError(f"PDF contains no selectable text and OCR failed: {str(ocr_err)}")
                elif ext in ['png', 'jpg', 'jpeg', 'webp']:
                    mime_map = {
                        'png': 'image/png',
                        'jpg': 'image/jpeg',
                        'jpeg': 'image/jpeg',
                        'webp': 'image/webp'
                    }
                    mime_type = mime_map.get(ext, 'image/jpeg')
                    try:
                        raw_text = await ocr_document_fallback(file_bytes, mime_type)
                    except Exception as ocr_err:
                        raise ValueError(f"Image OCR extraction failed: {str(ocr_err)}")
                else:
                    raise ValueError("The parsed file contains no text. Please ensure the document has readable content.")
                
            # Release raw binary memory immediately
            del file_bytes

            if not raw_text.strip():
                raise ValueError("No text could be extracted from this document.")

            # Calculate similarity (Gemini zero-RAM embedding or cached lightweight local vector)
            match_score = await asyncio.to_thread(calculate_similarity, raw_text, jd_embedding)
            
            # Generate recruiter feedback (Gemini API) asynchronously
            analysis = await analyze_resume_fit(raw_text, final_jd)
            
            return {
                "filename": file.filename,
                "status": "success",
                "match_score": match_score,
                "analysis": analysis,
                "raw_text": raw_text
            }
            
        except Exception as e:
            return {
                "filename": file.filename,
                "status": "error",
                "error_message": str(e)
            }


@router.post("/match")
async def match_resumes(
    files: List[UploadFile] = File(...),
    job_description: str = Form(...)
):
    """
    Accepts multiple resume files (PDF or DOCX) and a job description 
    (either full text or a simple job title keyword).
    
    Processes all candidates concurrently with controlled concurrency
    to prevent memory exhaustion while delivering fast parallel response times.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
        
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Maximum of {MAX_FILES} files allowed per request.")
        
    jd_input = job_description.strip()
    if not jd_input:
        raise HTTPException(status_code=400, detail="Job description input cannot be empty.")
        
    # 1. Check if we need to expand the Job Description (if it's a short title like 'SDE II')
    is_expanded = False
    final_jd = jd_input
    if len(jd_input) < 50:
        final_jd = await generate_jd_from_title(jd_input)
        is_expanded = True

    # 2. Pre-calculate Job Description embedding once to avoid redundant computations
    jd_embedding = await asyncio.to_thread(get_embedding, final_jd)

    # 3. Concurrently process resumes via Semaphore pool
    tasks = [process_single_resume(file, final_jd, jd_embedding) for file in files]
    results = await asyncio.gather(*tasks)
            
    # Sort results by match score in descending order (highest score first)
    results.sort(key=lambda x: x.get("match_score", -1.0), reverse=True)
            
    return {
        "job_description_used": final_jd,
        "is_job_description_expanded": is_expanded,
        "results": results
    }



