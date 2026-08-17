import os
import math
from app.config import settings

_local_model = None

def _get_local_model():
    global _local_model
    if _local_model is None:
        import torch
        from sentence_transformers import SentenceTransformer
        # Optimize PyTorch memory footprint for low-memory environments (Render 512MB)
        torch.set_num_threads(2)
        # Use lightweight 80MB model by default to prevent OOM
        model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        _local_model = SentenceTransformer(model_name)
    return _local_model

def get_embedding(text: str):
    """
    Converts a string of text into an embedding vector.
    Uses Gemini text-embedding-004 (0 MB RAM overhead on server) when available,
    falling back to a lazy-loaded lightweight local SentenceTransformer.
    """
    clean_text = text.strip() if text else ""
    if not clean_text:
        return [0.0] * 768

    # 1. Primary: Gemini Embeddings API (Zero RAM on server)
    if settings.GEMINI_API_KEY:
        try:
            import google.generativeai as genai
            res = genai.embed_content(
                model="models/text-embedding-004",
                content=clean_text[:8000],
                task_type="retrieval_document"
            )
            if "embedding" in res and res["embedding"]:
                return res["embedding"]
        except Exception:
            pass

    # 2. Local Fallback (Lazy loaded in memory)
    model = _get_local_model()
    emb = model.encode(clean_text, normalize_embeddings=True)
    return emb.tolist() if hasattr(emb, "tolist") else list(emb)

def calculate_similarity(resume_text: str, jd_text_or_emb) -> float:
    """
    Calculates the cosine similarity between the resume text and the job description.
    Accepts either raw job description text (str) or a pre-computed embedding list/tensor.
    Uses pure-math dot product (instant execution, zero memory overhead).
    Returns a percentage score between 0.0 and 100.0.
    """
    if not resume_text.strip():
        return 0.0

    # 1. Compute resume embedding
    resume_emb = get_embedding(resume_text)
    
    # 2. Resolve JD embedding
    if isinstance(jd_text_or_emb, str):
        jd_emb = get_embedding(jd_text_or_emb)
    elif isinstance(jd_text_or_emb, (list, tuple)):
        jd_emb = jd_text_or_emb
    else:
        jd_emb = jd_text_or_emb.tolist() if hasattr(jd_text_or_emb, "tolist") else list(jd_text_or_emb)

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


