import os
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

class Settings:
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    PORT: int = int(os.getenv("PORT", 8000))
    HOST: str = os.getenv("HOST", "0.0.0.0")

    def validate(self):
        if not self.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set in the environment or .env file.")
        if not isinstance(self.PORT, int) or self.PORT < 1 or self.PORT > 65535:
            raise ValueError(f"Invalid PORT: {self.PORT}. Must be between 1-65535")

settings = Settings()
