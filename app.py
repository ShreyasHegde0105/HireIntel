import uvicorn
import os
from app.main import app

if __name__ == "__main__":
    # Hugging Face Spaces always routes traffic to port 7860
    port = int(os.environ.get("PORT", 7860))
    
    print(f"Starting FastAPI backend on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
