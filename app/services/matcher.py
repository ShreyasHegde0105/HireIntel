from sentence_transformers import SentenceTransformer, util

# Initialize the SentenceTransformer model.
# It downloads once during server startup and remains in RAM for fast, instant matching.
# "nomic-ai/nomic-embed-text-v1.5" is an Apache-2.0 licensed model supporting an 8,192-token context window.
model = SentenceTransformer("nomic-ai/nomic-embed-text-v1.5", trust_remote_code=True)


def get_embedding(text: str):
    """
    Converts a string of text into a mathematical vector representation (embedding).
    """
    return model.encode(text, convert_to_tensor=True)

def calculate_similarity(resume_text: str, jd_text_or_emb) -> float:
    """
    Calculates the cosine similarity between the resume text and the job description.
    Accepts either raw job description text (str) or a pre-computed embedding tensor.
    Returns a percentage score between 0.0 and 100.0.
    """
    if not resume_text.strip():
        return 0.0

    # 1. Generate the resume embedding
    resume_emb = get_embedding(resume_text)
    
    # 2. Use pre-computed JD embedding if provided, otherwise compute it
    if isinstance(jd_text_or_emb, str):
        jd_emb = get_embedding(jd_text_or_emb)
    else:
        jd_emb = jd_text_or_emb
    
    # 3. Compute Cosine Similarity between the two vectors
    similarity_tensor = util.cos_sim(resume_emb, jd_emb)
    
    # 4. Extract the score, clamp it between 0 and 1, and turn it into a percentage
    score = float(similarity_tensor.item())
    percentage_score = max(0.0, min(1.0, score)) * 100
    
    return round(percentage_score, 2)

