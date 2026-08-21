FROM python:3.10-slim

# Set environment variables for minimal memory and fast execution
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MALLOC_TRIM_THRESHOLD_=100000 \
    PORT=7860

# Set working directory in container
WORKDIR /code

# Install minimal system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt /code/requirements.txt

# Install lightweight python dependencies (no PyTorch, ~20s build)
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copy application code to container
COPY ./app /code/app

# Expose port
EXPOSE 7860

# Run Uvicorn ASGI server with 1 worker to keep RAM strictly low (<130MB)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
