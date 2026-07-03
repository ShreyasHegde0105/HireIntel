from sentence_transformers import SentenceTransformer, util

# Initialize the SentenceTransformer model.
# It downloads once during server startup and remains in RAM for fast, instant matching.
# "all-MiniLM-L6-v2" is a highly efficient 384-dimensional model, ideal for local CPU runtimes.
model = SentenceTransformer("all-MiniLM-L6-v2")

def get_embedding(text: str):
    """
    Converts a string of text into a mathematical vector representation (embedding).
    """
    return model.encode(text, convert_to_tensor=True)

def calculate_similarity(resume_text: str, jd_text: str) -> float:
    """
    Calculates the cosine similarity between the resume text and the job description.
    Returns a percentage score between 0.0 and 100.0.
    """
    if not resume_text.strip() or not jd_text.strip():
        return 0.0

    # 1. Generate the embeddings (lists of numbers representing semantic meaning)
    resume_emb = get_embedding(resume_text)
    jd_emb = get_embedding(jd_text)
    
    # 2. Compute Cosine Similarity between the two vectors
    similarity_tensor = util.cos_sim(resume_emb, jd_emb)
    
    # 3. Extract the score, clamp it between 0 and 1, and turn it into a percentage
    score = float(similarity_tensor.item())
    percentage_score = max(0.0, min(1.0, score)) * 100
    
    return round(percentage_score, 2)
