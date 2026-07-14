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
    settings.validate()  # Ensure the API key is set
    
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    current_year = datetime.now().year
    prompt = f"""
    You are an expert technical recruiter. Analyze the following candidate resume against the provided job description.
    
    CRITICAL: For all academic, timeline, graduation, and experience calculations, assume the current year is {current_year}.
    
    Job Description:
    {jd_text}
    
    Candidate Resume:
    {resume_text}
    """

    
    try:
        # Request a structured JSON response matching the Pydantic schema asynchronously
        response = await model.generate_content_async(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": ResumeAnalysisSchema
            }
        )
        return json.loads(response.text)
    except Exception as e:
        # Fallback response in case of API failure or missing keys
        return {
            "summary": "Could not generate analysis. Please check your API key configuration.",
            "strengths": [],
            "gaps": ["Gemini API analysis failed."],
            "recommendations": ["Check if your Gemini API key is valid and you have quota left."],
            "match_explanation": f"API Error detail: {str(e)}"
        }

async def generate_jd_from_title(job_title: str) -> str:
    """
    If the user enters a simple job title or keyword instead of a full job description,
    this function uses Gemini to expand it into a detailed, standard job description asynchronously.
    """
    settings.validate()
    
    model = genai.GenerativeModel("gemini-2.5-flash")
    
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
    
    try:
        response = await model.generate_content_async(prompt)
        return response.text.strip()
    except Exception as e:
        # Fallback in case of API failure
        return f"Standard Job Description for {job_title}.\n(Could not retrieve full details due to API error: {str(e)})"

async def ocr_document_fallback(file_bytes: bytes, mime_type: str) -> str:
    """
    Uses Gemini 2.5 Flash's multimodal capabilities to perform OCR on a scanned document or image in-memory.
    Extracts and returns the text content.
    """
    settings.validate()
    
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    prompt = """
    You are a professional document text extractor.
    Your task is to perform OCR on the attached document and extract all of its text content.
    Extract the text exactly as it appears in the document.
    Return ONLY the extracted text content. Do not include any greeting, markdown formatting, or comments.
    """
    
    try:
        response = await model.generate_content_async(
            [
                {"mime_type": mime_type, "data": file_bytes},
                prompt
            ]
        )
        return response.text.strip()
    except Exception as e:
        raise RuntimeError(f"OCR Fallback failed: {str(e)}")

async def ocr_pdf_fallback(file_bytes: bytes) -> str:
    """
    Wrapper function for PDF OCR fallback, calling ocr_document_fallback with 'application/pdf'.
    """
    return await ocr_document_fallback(file_bytes, "application/pdf")



