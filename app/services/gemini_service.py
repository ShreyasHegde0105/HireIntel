import json
from datetime import datetime
from typing import List
from pydantic import BaseModel, Field

import google.generativeai as genai
from app.config import settings

# Configure Gemini with the API Key
if settings.GEMINI_API_KEY:
    genai.configure(api_key=settings.GEMINI_API_KEY)

# Define the structured schema we want Gemini to return
class ResumeAnalysisSchema(BaseModel):
    summary: str = Field(description="A brief 2-3 sentence professional summary of the candidate's background relative to the job.")
    strengths: List[str] = Field(description="List of 3 key strengths or matching skills the candidate possesses for this role.")
    gaps: List[str] = Field(description="List of core requirements or skills from the job description that are missing in the resume.")
    recommendations: List[str] = Field(description="Actionable improvement tips for the candidate's resume to better fit this specific role.")
    match_explanation: str = Field(description="A clear, logical explanation for why the candidate matches at this level.")

async def analyze_resume_fit(resume_text: str, jd_text: str) -> dict:
    """
    Sends the resume and job description text to the Gemini API to get
    structured feedback, strengths, gaps, and recommendations asynchronously.
    """
    current_year = datetime.now().year
    prompt = f"""
    You are an expert technical recruiter. Analyze the following candidate resume against the provided job description.
    
    CRITICAL: For all academic, timeline, graduation, and experience calculations, assume the current year is {current_year}.
    
    Job Description:
    {jd_text}
    
    Candidate Resume:
    {resume_text}
    """

    candidate_models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    last_error = None
    
    for model_name in candidate_models:
        try:
            model = genai.GenerativeModel(model_name)
            response = await model.generate_content_async(
                prompt,
                generation_config={
                    "response_mime_type": "application/json",
                    "response_schema": ResumeAnalysisSchema
                }
            )
            return json.loads(response.text)
        except Exception as e:
            last_error = e
            continue

    # Fallback response in case of API failure or missing keys / quota exhausted
    err_str = str(last_error) if last_error else "Unknown error"
    return {
        "summary": "AI summary temporarily unavailable (check Gemini API key or quota).",
        "strengths": ["Parsed and matched via high-context semantic vector similarity."],
        "gaps": ["Detailed LLM gap extraction requires an active Gemini API key with available quota."],
        "recommendations": ["Ensure your Gemini API key from Google AI Studio is active and within quota limits."],
        "match_explanation": f"Note: Semantic match score was computed locally. Gemini feedback note: {err_str[:120]}"
    }


async def generate_jd_from_title(job_title: str) -> str:
    """
    If the user enters a simple job title or keyword instead of a full job description,
    this function uses Gemini to expand it into a detailed, standard job description asynchronously.
    """
    prompt = f"""
    You are an expert technical recruiter and writer.
    The user provided a short job title/keyword: "{job_title}".
    Please expand this into a comprehensive, standard Job Description.
    It must include:
    - Role Summary
    - Key Responsibilities
    - Required Core Technical Skills
    - Preferred Qualifications
    
    Keep the output clean and professional.
    """
    
    candidate_models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    last_err = None
    for model_name in candidate_models:
        try:
            model = genai.GenerativeModel(model_name)
            response = await model.generate_content_async(prompt)
            if response.text:
                return response.text.strip()
        except Exception as e:
            last_err = e
            continue

    return f"Standard Job Description for {job_title}.\n(Role Summary, Responsibilities, Core Skills, and Qualifications for {job_title})"

async def ocr_document_fallback(file_bytes: bytes, mime_type: str) -> str:
    """
    Uses Gemini's multimodal capabilities to perform OCR on a scanned document or image in-memory.
    Extracts and returns the text content.
    """
    prompt = """
    You are a professional document text extractor.
    Your task is to perform OCR on the attached document and extract all of its text content.
    Extract the text exactly as it appears in the document.
    Return ONLY the extracted text content. Do not include any greeting, markdown formatting, or comments.
    """
    
    candidate_models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    last_err = None
    for model_name in candidate_models:
        try:
            model = genai.GenerativeModel(model_name)
            response = await model.generate_content_async(
                [
                    {"mime_type": mime_type, "data": file_bytes},
                    prompt
                ]
            )
            if response.text:
                return response.text.strip()
        except Exception as e:
            last_err = e
            continue
            
    raise RuntimeError(f"OCR Fallback failed: {str(last_err)}")

async def ocr_pdf_fallback(file_bytes: bytes) -> str:
    """
    Wrapper function for PDF OCR fallback, calling ocr_document_fallback with 'application/pdf'.
    """
    return await ocr_document_fallback(file_bytes, "application/pdf")




