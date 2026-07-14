from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import resume
from app.config import settings

# Initialize the FastAPI App
app = FastAPI(
    title="Semantic Resume Matching & RAG API",
    description="Backend API for parsing and ranking resumes using local SentenceTransformers and the Gemini 1.5 Flash API.",
    version="1.0.0"
)

# Configure CORS (Cross-Origin Resource Sharing)
# This is crucial so that our HTML/JS frontend (even if opened locally or served from a different port)
# is allowed to send requests and upload files to this backend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins for local development
    allow_credentials=True,
    allow_methods=["*"],  # Allows all HTTP methods (POST, GET, OPTIONS, etc.)
    allow_headers=["*"],  # Allows all HTTP headers
)

# Register our resume router (mounts all the resume routes we created under /api)
app.include_router(resume.router)

@app.on_event("startup")
def startup_event():
    """
    Validate settings immediately at server startup.
    Fails early if critical environment keys (e.g. GEMINI_API_KEY) are missing.
    """
    settings.validate()


@app.get("/")
def read_root():
    """
    Basic health check / entry point route.
    """
    return {
        "status": "online",
        "message": "Welcome to the Semantic Resume Matching API. Navigate to /docs for interactive API documentation."
    }

if __name__ == "__main__":
    import uvicorn
    # Run the server (allows running python app/main.py directly)
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)
