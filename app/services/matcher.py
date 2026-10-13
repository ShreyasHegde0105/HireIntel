import asyncio
import hashlib
import logging
import math
from collections import OrderedDict
from typing import List

from google.genai import types

from app.config import settings
from app.services.ai_client import get_client

logger = logging.getLogger(__name__)


class EmbeddingUnavailableError(Exception):
    """Raised when an embedding could not be computed. Never replaced by a zero vector."""


# Only successful embeddings are cached. Least-recently-used entries are evicted first.
_embedding_cache: "OrderedDict[str, List[float]]" = OrderedDict()
MAX_CACHE_SIZE = 128


def _cache_key(text: str) -> str:
    raw = f"{settings.EMBEDDING_MODEL}|{settings.EMBEDDING_DIMENSIONS}|{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _as_query(jd_text: str) -> str:
    # gemini-embedding-2 takes no task_type; the task goes in a text prefix.
    # See https://ai.google.dev/gemini-api/docs/embeddings
    return f"task: search result | query: {jd_text}"


def _as_document(resume_text: str) -> str:
    return f"title: none | text: {resume_text}"


async def _embed(text: str) -> List[float]:
    key = _cache_key(text)
    cached = _embedding_cache.get(key)
    if cached is not None:
        _embedding_cache.move_to_end(key)
        return cached

    try:
        response = await asyncio.wait_for(
            get_client().aio.models.embed_content(
                model=settings.EMBEDDING_MODEL,
                contents=text,
                config=types.EmbedContentConfig(output_dimensionality=settings.EMBEDDING_DIMENSIONS),
            ),
            timeout=settings.EMBEDDING_TIMEOUT,
        )
        values = list(response.embeddings[0].values or [])
    except asyncio.TimeoutError:
        logger.warning("embedding timed out", extra={"model": settings.EMBEDDING_MODEL})
        raise EmbeddingUnavailableError("Similarity scoring timed out.") from None
    except Exception as e:
        logger.warning(
            "embedding failed",
            extra={"model": settings.EMBEDDING_MODEL, "error": type(e).__name__, "detail": str(e)[:300]},
        )
        raise EmbeddingUnavailableError("Similarity scoring is temporarily unavailable.") from e

    if not values or not any(values):
        logger.warning("embedding was empty", extra={"model": settings.EMBEDDING_MODEL})
        raise EmbeddingUnavailableError("Similarity scoring returned no result.")

    _embedding_cache[key] = values
    if len(_embedding_cache) > MAX_CACHE_SIZE:
        _embedding_cache.popitem(last=False)
    return values


async def embed_job_description(jd_text: str) -> List[float]:
    return await _embed(_as_query(jd_text[: settings.MAX_EMBEDDING_CHARS]))


async def embed_resume(resume_text: str) -> List[float]:
    return await _embed(_as_document(resume_text[: settings.MAX_EMBEDDING_CHARS]))


def cosine_similarity_score(a: List[float], b: List[float]) -> float:
    """Cosine similarity mapped to 0-100. This is a similarity measure, not a probability of fit."""
    if len(a) != len(b):
        raise EmbeddingUnavailableError("Embedding sizes do not match.")
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        raise EmbeddingUnavailableError("Similarity scoring returned no result.")
    score = sum(x * y for x, y in zip(a, b, strict=True)) / (norm_a * norm_b)
    return round(max(0.0, min(1.0, score)) * 100, 1)
