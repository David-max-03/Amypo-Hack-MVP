"""FastAPI application for the Code Titans PS8 + PS2 integrated trust pipeline.

Run with:  uvicorn backend.app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import routes_health, routes_jobs, routes_pipeline, routes_ps2, routes_ps8, routes_storage
from .config import settings
from .core import storage
from .core.embeddings import embeddings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)-38s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DESCRIPTION = """
**Code Titans — HackWithAMYPO 2026 Stage 2 MVP**

Two problem statements wired into one pipeline:

* **PS8** — Assignment Question Iteration & Variation Generation
* **PS2** — AI Hallucination Detection & Reliability Scoring

```
seed -> parse -> plan -> generate (Qwen2.5-Coder 7B via Ollama)
     -> PS8 structural validation -> PS2 reliability verification
     -> decision -> PASS | REVIEW | REJECT -> (regenerate on REJECT)
```

Everything runs locally. No paid third-party APIs are used anywhere.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.ensure_data_files()

    # Warm the embedding model on a background thread. The first MiniLM call takes
    # seconds; doing it here keeps the first real request inside PS2's latency
    # budget, and doing it off-thread means the server still binds immediately.
    def _warm() -> None:
        try:
            embeddings.warm_up()
            logger.info("Embedding backend ready: %s", embeddings.backend)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Embedding warm-up failed: %s", exc)

    threading.Thread(target=_warm, name="embedding-warmup", daemon=True).start()

    logger.info("Ollama host=%s model=%s", settings.ollama_host, settings.ollama_model)
    logger.info("Data directory: %s", settings.data_dir)
    yield


app = FastAPI(
    title="Code Titans — PS8 + PS2 Question Trust Pipeline",
    description=DESCRIPTION,
    version=routes_health.API_VERSION,
    lifespan=lifespan,
)

# The React dev server runs on a different port, so CORS is required for the demo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:3000", "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
app.include_router(routes_health.router, prefix=API_PREFIX)
app.include_router(routes_ps8.router, prefix=API_PREFIX)
app.include_router(routes_ps2.router, prefix=API_PREFIX)
app.include_router(routes_pipeline.router, prefix=API_PREFIX)
app.include_router(routes_storage.router, prefix=API_PREFIX)
app.include_router(routes_jobs.router, prefix=API_PREFIX)


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {
        "name": "Code Titans — PS8 + PS2 Question Trust Pipeline",
        "version": routes_health.API_VERSION,
        "docs": "/docs",
        "health": f"{API_PREFIX}/health",
    }
