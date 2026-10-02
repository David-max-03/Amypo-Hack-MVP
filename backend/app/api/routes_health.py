"""Health endpoint, shared by both problem statements."""

from __future__ import annotations

from fastapi import APIRouter

from ..config import settings
from ..core import storage
from ..core.embeddings import embeddings
from ..core.entailment import entailment
from ..core.ollama_client import ollama
from ..ps2.source_verification import corpus
from ..schemas import HealthResponse

router = APIRouter(tags=["System"])

API_VERSION = "1.0.0"


@router.get("/health", response_model=HealthResponse, summary="System health")
def health() -> HealthResponse:
    """Report what is actually available, so a demo never silently degrades.

    Status is "degraded" (not "ok") whenever generation is impossible or PS2 is
    running on the fallback vectoriser instead of MiniLM.
    """
    ollama_status = ollama.status()
    corpus_stats = corpus.stats()

    embedding_info = {
        "backend": embeddings.backend,
        "is_minilm": embeddings.is_minilm,
        "configured_model": settings.embedding_model,
        "load_error": embeddings.load_error,
        # The model that decides whether a corpus sentence agrees with a claim.
        "entailment": {
            "backend": entailment.backend,
            "available": entailment.available,
            "configured_model": settings.entailment_model,
            "load_error": entailment.load_error,
        },
    }

    degraded = (
        not ollama_status.reachable
        or not ollama_status.model_available
        or not embeddings.is_minilm
        or corpus_stats["entry_count"] == 0
    )

    return HealthResponse(
        status="degraded" if degraded else "ok",
        version=API_VERSION,
        ollama={
            "reachable": ollama_status.reachable,
            "host": ollama_status.host,
            "model": ollama_status.model,
            "model_available": ollama_status.model_available,
            "models_present": ollama_status.models_present,
            "detail": ollama_status.detail,
        },
        embeddings=embedding_info,
        corpus=corpus_stats,
        storage={
            "data_dir": str(settings.data_dir),
            "accepted_questions": len(storage.load_question_bank()),
            "review_queue": len(storage.load_review_queue()),
        },
        config={
            "pass_reliability_min": settings.pass_reliability_min,
            "review_reliability_min": settings.review_reliability_min,
            "duplicate_semantic_max": settings.duplicate_semantic_max,
            "duplicate_lexical_max": settings.duplicate_lexical_max,
            "max_regeneration_attempts": settings.max_regeneration_attempts,
            "self_consistency_samples": settings.self_consistency_samples,
            "ps2_target_latency_s": settings.ps2_target_latency_s,
            "reliability_weights": settings.reliability_weights,
        },
    )
