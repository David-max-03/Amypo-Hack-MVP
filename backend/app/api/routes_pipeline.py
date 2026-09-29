"""The integrated PS8 + PS2 endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ..pipeline import run_pipeline
from ..schemas import GenerateAndVerifyRequest, GenerateAndVerifyResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Integrated"])


@router.post(
    "/generate-and-verify",
    response_model=GenerateAndVerifyResponse,
    summary="Run the full pipeline: generate -> validate -> verify -> decide -> regenerate",
)
def generate_and_verify(request: GenerateAndVerifyRequest) -> GenerateAndVerifyResponse:
    """Execute the complete Code Titans trust pipeline for one seed question."""
    seed, results, summary, timings, warnings = run_pipeline(
        request.seed_question,
        request.domain,
        request.count,
        difficulty_shift=request.difficulty_shift,
        enable_regeneration=request.enable_regeneration,
        verify=True,
        persist=request.persist,
    )

    if not results and warnings:
        raise HTTPException(status_code=503, detail=warnings[0])

    return GenerateAndVerifyResponse(
        seed_metadata=seed,
        results=results,
        summary=summary,
        timings_ms=timings,
        warnings=warnings,
    )
