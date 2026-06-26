# Slim, CPU-only image. No model weights are baked in (optional LLM is called
# over HTTP), so the image stays small and starts well within the 60s readiness gate.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code.
COPY app ./app

EXPOSE 8000

# Bind to 0.0.0.0 and honor the platform-injected $PORT (Railway sets it).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
