import uvicorn
import os
from app.config import settings
from app.main import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", settings.PORT))
    host = os.environ.get("HOST", settings.HOST)
    
    print(f"Starting FastAPI backend on {host}:{port}...")
    uvicorn.run(app, host=host, port=port)

