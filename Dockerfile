FROM python:3.10-slim

# Set environment variables for Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/tmp/huggingface_cache

# Set working directory in container
WORKDIR /code

# Install system dependencies (needed for certain PDF/image libraries if any)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt /code/requirements.txt

# Install python dependencies
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Pre-download the Hugging Face model during Docker build to ensure instant container startup
# The model will be cached in the Docker image layers.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)"

# Copy application code to container
COPY ./app /code/app

# Expose port 7860 (Hugging Face Spaces default port)
EXPOSE 7860

# Run Uvicorn ASGI server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
