from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import List
import asyncio
from app.services.parser import extract_text
from app.services.matcher import calculate_similarity
from app.services.gemini_service import analyze_resume_fit, generate_jd_from_title

router = APIRouter(prefix="/api", tags=["Resumes"])

async def process_single_resume(file: UploadFile, final_jd: str) -> dict:
    """
    Parses, embed-matches, and requests AI diagnostics for a single resume in-memory.
    """
    try:
        # Read file stream directly into memory bytes
        file_bytes = await file.read()
        
        # Extract plain text
        raw_text = extract_text(file_bytes, file.filename)
        
        if not raw_text.strip():
            raise ValueError("The parsed file contains no text. Check if the document is scanned or empty.")
            
        # Calculate similarity locally (SentenceTransformers)
        match_score = calculate_similarity(raw_text, final_jd)
        
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
        
    jd_input = job_description.strip()
    if not jd_input:
        raise HTTPException(status_code=400, detail="Job description input cannot be empty.")
        
    # 1. Check if we need to expand the Job Description (if it's a short title like 'SDE II')
    is_expanded = False
    final_jd = jd_input
    if len(jd_input) < 50:
        final_jd = await generate_jd_from_title(jd_input)
        is_expanded = True

    # 2. Concurrently process all resumes using asyncio.gather
    # This runs the API requests to Gemini in parallel instead of one after another.
    tasks = [process_single_resume(file, final_jd) for file in files]
    results = await asyncio.gather(*tasks)
            
    # Sort results by match score in descending order (highest score first)
    # Errors (no match score) are placed at the bottom
    results.sort(key=lambda x: x.get("match_score", -1.0), reverse=True)
            
    return {
        "job_description_used": final_jd,
        "is_job_description_expanded": is_expanded,
        "results": results
    }

