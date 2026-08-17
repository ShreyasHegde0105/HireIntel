from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import List
import asyncio
from app.services.parser import extract_text
from app.services.matcher import calculate_similarity, get_embedding
from app.services.gemini_service import analyze_resume_fit, generate_jd_from_title, ocr_pdf_fallback, ocr_document_fallback

router = APIRouter(prefix="/api", tags=["Resumes"])

MAX_FILES = 20
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

async def process_single_resume(file: UploadFile, final_jd: str, jd_embedding) -> dict:
    """
    Parses, embed-matches, and requests AI diagnostics for a single resume in-memory.
    """
    try:
        # Check file size before loading full contents (using the underlying synchronous file object)
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        
        if file_size > MAX_FILE_SIZE:
            raise ValueError(f"File exceeds the 5MB size limit ({round(file_size / (1024 * 1024), 2)}MB uploaded).")

        # Read file stream directly into memory bytes
        file_bytes = await file.read()
        
        # Extract plain text (offloaded to thread to prevent blocking event loop)
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
            
        if not raw_text.strip():
            raise ValueError("No text could be extracted from this document.")

        # Calculate similarity locally (SentenceTransformers) in thread with pre-computed embedding
        match_score = await asyncio.to_thread(calculate_similarity, raw_text, jd_embedding)
        
        # Generate recruiter feedback (Gemini API) asynchronously
        analysis = await analyze_resume_fit(raw_text, final_jd)
        
        return {
            "filename": file.filename,
            "status": "success",
            "match_score": match_score,
            "analysis": analysis,
            "raw_text": raw_text  # Returned so the frontend can offer a toggle-to-view option
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
    
    Processes all candidates concurrently using asyncio tasks to prevent 
    sequential API blockages and reduce latency.
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

    # 2. Pre-calculate the Job Description embedding once to avoid redundant computations for each resume
    # Done inside asyncio.to_thread since model.encode is CPU-bound
    jd_embedding = await asyncio.to_thread(get_embedding, final_jd)

    # 3. Concurrently process all resumes using asyncio.gather
    # This runs the API requests to Gemini in parallel instead of one after another.
    tasks = [process_single_resume(file, final_jd, jd_embedding) for file in files]
    results = await asyncio.gather(*tasks)
            
    # Sort results by match score in descending order (highest score first)
    # Errors (no match score) are placed at the bottom
    results.sort(key=lambda x: x.get("match_score", -1.0), reverse=True)
            
    return {
        "job_description_used": final_jd,
        "is_job_description_expanded": is_expanded,
        "results": results
    }


