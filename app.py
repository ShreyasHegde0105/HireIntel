import uvicorn

from app.config import settings
from app.main import app

if __name__ == "__main__":
    uvicorn.run(app, host=settings.HOST, port=settings.PORT, proxy_headers=True)
