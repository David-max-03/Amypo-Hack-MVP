"""PS2 endpoints: /verify and the demo problematic-response fixtures."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..core import storage
from ..ps2 import engine as ps2_engine
from ..schemas import VerifyRequest, VerifyResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["PS2"])


@router.post(
    "/verify",
    response_model=VerifyResponse,
    summary="PS2: verify an AI response for hallucination and reliability",
)
def verify(request: VerifyRequest) -> VerifyResponse:
    """Analyse one AI-generated response and return a reliability verdict."""
    verification = ps2_engine.verify_text(
        request.response_text,
        source_context=request.source_context,
        question=request.question,
        answer_text=request.response_text,
    )

    total_ms = verification.timings_ms.get("total_ms", 0.0)
    within_budget = total_ms <= settings.ps2_target_latency_s * 1000.0
    if not within_budget:
        logger.warning(
            "PS2 verification took %.0f ms, over the %.0f ms budget "
            "(usually a cold embedding-model load)",
            total_ms,
            settings.ps2_target_latency_s * 1000.0,
        )

    storage.audit(
        "ps2_verify",
        verdict=verification.verdict,
        reliability_score=verification.reliability_score,
        hallucination_probability=verification.hallucination_probability,
        flagged_spans=len(verification.flagged_spans),
        analysis_ms=total_ms,
    )

    return VerifyResponse(
        reliability_score=verification.reliability_score,
        hallucination_probability=verification.hallucination_probability,
        verdict=verification.verdict,
        flagged_spans=verification.flagged_spans,
        confidence_score=verification.confidence_score,
        evidence=verification.evidence,
        claims=verification.claims,
        contradictions=verification.contradictions,
        signals=verification.signals,
        reasons=verification.reasons,
        recommendations=verification.recommendations,
        embedding_backend=verification.embedding_backend,
        analysis_time_ms=total_ms,
        within_latency_budget=within_budget,
    )


@router.get("/demo/problematic-responses", summary="Demo fixtures for PS2")
def problematic_responses() -> dict:
    """Curated responses that demonstrate PS2 detecting specific problems.

    These are fixtures for the demo and the test suite, not benchmark results.
    """
    path = settings.data_dir / "demo" / "problematic_responses.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="demo fixtures not found")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@router.get("/corpus/stats", summary="Reference corpus statistics")
def corpus_stats() -> dict:
    from ..ps2.source_verification import corpus

    return corpus.stats()
