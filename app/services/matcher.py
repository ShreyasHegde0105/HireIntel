import math
import hashlib
from typing import List, Union
import google.generativeai as genai
from app.config import settings

if settings.GEMINI_API_KEY:
    genai.configure(api_key=settings.GEMINI_API_KEY)

_embedding_cache = {}  # In-memory LRU-like cache (limited size) to avoid re-embedding identical texts
MAX_CACHE_SIZE = 128

def _get_cache_key(text: str) -> str:
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def get_embedding(text: str) -> List[float]:
    """
    Converts a string of text into a 768-dimensional embedding vector
    using Google's Gemini text-embedding-004 model (0 MB RAM overhead on server).
    Includes an in-memory MD5 cache to avoid recomputing identical texts.
    """
    clean_text = text.strip() if text else ""
    if not clean_text:
        return [0.0] * 768

    cache_key = _get_cache_key(clean_text)
    if cache_key in _embedding_cache:
        return _embedding_cache[cache_key]

    embedding = None

    if settings.GEMINI_API_KEY:
        try:
            res = genai.embed_content(
                model="models/text-embedding-004",
                content=clean_text[:8000],
                task_type="retrieval_document"
            )
            if "embedding" in res and res["embedding"]:
                embedding = res["embedding"]
        except Exception as e:
            print(f"Gemini embedding error: {e}")

    # Fallback to zero vector if API call fails
    if embedding is None:
        embedding = [0.0] * 768

    # Save to memory cache (keep size bounded)
    if len(_embedding_cache) >= MAX_CACHE_SIZE:
        _embedding_cache.pop(next(iter(_embedding_cache)))
    _embedding_cache[cache_key] = embedding

    return embedding

def calculate_similarity(resume_text: str, jd_text_or_emb: Union[str, List[float]]) -> float:
    """
    Calculates cosine similarity between resume text and job description.
    Accepts either raw job description text (str) or a pre-computed embedding list.
    Uses pure-math dot product (instant execution, zero memory overhead).
    Returns a percentage score between 0.0 and 100.0.
    """
    if not resume_text or not resume_text.strip():
        return 0.0

    # 1. Compute resume embedding
    resume_emb = get_embedding(resume_text)
    
    # 2. Resolve JD embedding
    if isinstance(jd_text_or_emb, str):
        jd_emb = get_embedding(jd_text_or_emb)
    elif isinstance(jd_text_or_emb, (list, tuple)):
        jd_emb = jd_text_or_emb
    else:
        jd_emb = list(jd_text_or_emb)

    # 3. Fast Vector Cosine Similarity
    dot = sum(a * b for a, b in zip(resume_emb, jd_emb))
    norm_a = math.sqrt(sum(a * a for a in resume_emb))
    norm_b = math.sqrt(sum(b * b for b in jd_emb))
    
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
        
    score = dot / (norm_a * norm_b)
    
    # 4. Extract percentage score clamped between 0 and 100
    percentage_score = max(0.0, min(1.0, float(score))) * 100
    return round(percentage_score, 2)
