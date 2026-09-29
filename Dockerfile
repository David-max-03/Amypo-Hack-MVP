# Backend: FastAPI + PS8 generation/validation + PS2 verification.
# Ollama is NOT in this image - it runs on the host (see README "Docker").
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf-cache

WORKDIR /app

# CPU-only PyTorch first: the default wheel pulls ~2 GB of CUDA libraries that a
# MiniLM embedding model never uses.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the MiniLM weights into the image so the container starts offline and the
# first PS2 request is not a model download.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

COPY backend ./backend
COPY data ./data
COPY pytest.ini .

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
