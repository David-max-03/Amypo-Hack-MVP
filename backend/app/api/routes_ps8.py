"""PS8 endpoints: /generate, /domains, /strategies."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ..core import storage
from ..core.ollama_client import OllamaUnavailable
from ..core.timing import Stopwatch
from ..ps8 import domains as domain_registry
from ..ps8 import generation_engine, seed_parser, strategies, variation_planner
from ..ps8.validation.engine import compute_duplicate_rate, validate_candidate
from ..schemas import (
    DomainInfo,
    GenerateRequest,
    GenerateResponse,
    GenerateVariation,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["PS8"])


@router.get("/domains", response_model=list[DomainInfo], summary="List supported domains")
def get_domains() -> list[DomainInfo]:
    return [
        DomainInfo(
            id=d.id, label=d.label, description=d.description, example_seed=d.example_seed
        )
        for d in domain_registry.list_domains()
    ]


@router.get("/strategies", summary="List variation strategies")
def get_strategies() -> list[dict]:
    return [
        {
            "id": s.id,
            "label": s.label,
            "instruction": s.instruction,
            "preserve": s.preserve,
            "change": s.change,
        }
        for s in strategies.list_strategies()
    ]


@router.post(
    "/generate",
    response_model=GenerateResponse,
    summary="PS8: generate question variations from a seed",
)
def generate(request: GenerateRequest) -> GenerateResponse:
    """Generate variations and run PS8 structural validation on each.

    This is the PS8-only contract. It does NOT run PS2 verification - use
    /generate-and-verify for the integrated trust pipeline.
    """
    watch = Stopwatch()
    warnings: list[str] = []

    if not domain_registry.is_supported(request.domain):
        warnings.append(
            f"Domain {request.domain!r} is not in the supported list; "
            "the parser inferred one from the seed instead."
        )

    with watch.stage("ps8.seed_parsing"):
        seed = seed_parser.parse_seed(request.seed_question, request.domain)

    with watch.stage("ps8.variation_planning"):
        plan = variation_planner.plan_variations(
            seed, request.count, difficulty_shift=request.difficulty_shift
        )

    accepted = storage.accepted_question_texts()

    try:
        with watch.stage("ps8.generation"):
            outcome = generation_engine.generate_batch(
                seed,
                plan,
                difficulty_shift=request.difficulty_shift,
                known_questions=accepted,
            )
    except OllamaUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    warnings.extend(outcome.warnings)

    if not outcome.candidates:
        raise HTTPException(
            status_code=503,
            detail=(
                "No candidate could be generated. "
                + (outcome.warnings[0] if outcome.warnings else "Check that Ollama is running.")
            ),
        )

    variations: list[GenerateVariation] = []
    rejected: list[dict] = []
    kept_texts: list[str] = []

    with watch.stage("ps8.structural_validation"):
        for candidate in outcome.candidates:
            result = validate_candidate(
                candidate,
                seed,
                previously_generated=kept_texts,
                previously_accepted=accepted,
                difficulty_shift=request.difficulty_shift,
            )
            if not result.passed:
                rejected.append(
                    {
                        "question": candidate.question,
                        "variation_strategy": candidate.variation_strategy,
                        "reasons": result.reasons,
                    }
                )
                continue

            kept_texts.append(candidate.question)
            variations.append(
                GenerateVariation(
                    question=candidate.question,
                    answer_key=candidate.answer_key,
                    difficulty=candidate.difficulty_score,
                    id=candidate.id,
                    difficulty_label=candidate.difficulty,
                    domain=candidate.domain,
                    topic=candidate.topic,
                    subtopic=candidate.subtopic,
                    question_type=candidate.question_type,
                    learning_objective=candidate.learning_objective,
                    test_cases=candidate.test_cases,
                    variation_strategy=candidate.variation_strategy,
                    strategy_label=candidate.strategy_label,
                    structural_validation=result,
                )
            )

    duplicate_rate = compute_duplicate_rate([v.question for v in variations])

    storage.audit(
        "ps8_generate",
        seed=request.seed_question[:200],
        domain=seed.domain,
        requested=request.count,
        accepted=len(variations),
        rejected=len(rejected),
        duplicate_rate=duplicate_rate,
    )

    return GenerateResponse(
        variations=variations,
        duplicate_rate=duplicate_rate,
        requested_count=request.count,
        generated_count=len(outcome.candidates),
        accepted_count=len(variations),
        rejected_count=len(rejected),
        seed_metadata=seed,
        rejected=rejected,
        timings_ms=watch.as_dict(),
        warnings=warnings,
    )
