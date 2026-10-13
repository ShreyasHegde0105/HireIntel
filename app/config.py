import os

from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    try:
        return int(raw) if raw.strip() else default
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None


def _list_env(name: str, default: str) -> list:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


class Settings:
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    PORT: int = _int_env("PORT", 8000)
    HOST: str = os.getenv("HOST", "127.0.0.1")

    # Model IDs live here, never in service code. Check them against
    # https://ai.google.dev/gemini-api/docs/models when Google announces deprecations.
    # Generation models are tried in order; the first one that answers wins.
    GENERATION_MODELS: list = _list_env("GENERATION_MODELS", "gemini-3.5-flash-lite,gemini-3.8-flash")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "gemini-embedding-2")
    EMBEDDING_DIMENSIONS: int = _int_env("EMBEDDING_DIMENSIONS", 768)

    # Timeouts (seconds) per provider call
    EMBEDDING_TIMEOUT: int = _int_env("EMBEDDING_TIMEOUT", 20)
    ANALYSIS_TIMEOUT: int = _int_env("ANALYSIS_TIMEOUT", 60)
    OCR_TIMEOUT: int = _int_env("OCR_TIMEOUT", 60)
    # Total time for one AI call including retries and fallback models
    AI_CALL_BUDGET: int = _int_env("AI_CALL_BUDGET", 90)

    # Text sent to the models. Longer documents are cut and the result is flagged as truncated.
    MAX_ANALYSIS_CHARS: int = _int_env("MAX_ANALYSIS_CHARS", 30000)
    MAX_EMBEDDING_CHARS: int = _int_env("MAX_EMBEDDING_CHARS", 24000)

    # Upload limits
    MAX_FILES: int = _int_env("MAX_FILES", 10)
    MAX_FILE_SIZE_MB: int = _int_env("MAX_FILE_SIZE_MB", 5)
    MAX_JD_CHARS: int = _int_env("MAX_JD_CHARS", 20000)

    # Abuse and cost protection for the public demo
    RATE_LIMIT_PER_MINUTE: int = _int_env("RATE_LIMIT_PER_MINUTE", 3)
    RATE_LIMIT_PER_DAY: int = _int_env("RATE_LIMIT_PER_DAY", 20)
    DAILY_RESUME_BUDGET: int = _int_env("DAILY_RESUME_BUDGET", 150)
    DEMO_ACCESS_CODE: str = os.getenv("DEMO_ACCESS_CODE", "")

    # Comma-separated list of origins allowed to call the API from another domain.
    # Leave empty when the frontend is served by this app (same origin).
    CORS_ORIGINS: list = _list_env("CORS_ORIGINS", "")

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    def validate(self):
        if not self.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set in the environment or .env file.")
        if not 1 <= self.PORT <= 65535:
            raise ValueError(f"Invalid PORT: {self.PORT}. Must be between 1-65535")
        if not self.GENERATION_MODELS:
            raise ValueError("GENERATION_MODELS must list at least one model ID.")
        if "*" in self.CORS_ORIGINS:
            raise ValueError("CORS_ORIGINS must list explicit origins, not '*'.")


settings = Settings()
