"""PS8 endpoints: /generate, /domains, /strategies."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException

from ..core import storage
from ..core.ollama_client import OllamaUnavailable
from ..config import settings
from ..core.timing import Stopwatch
from ..ps8 import domains as domain_registry
from ..ps8 import generation_engine, seed_parser, strategies, variation_planner
from ..ps8.validation.engine import compute_duplicate_rate, validate_candidate
from ..schemas import (
    Candidate,
    DomainInfo,
    GenerateRequest,
    GenerateResponse,
    GenerateVariation,
    StructuralValidation,
    VariationPlanItem,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["PS8"])


@dataclass
class _Pending:
    """A rejected variation awaiting regeneration, with its attempt history."""

    candidate: Candidate
    item: VariationPlanItem
    result: StructuralValidation
    history: list[dict] = field(default_factory=list)


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
    regeneration_attempts = 0
    regenerated_accepted = 0

    def validate(candidate: Candidate) -> StructuralValidation:
        with watch.stage("ps8.structural_validation"):
            return validate_candidate(
                candidate,
                seed,
                previously_generated=kept_texts,
                previously_accepted=accepted,
                difficulty_shift=request.difficulty_shift,
            )

    def keep(candidate: Candidate, result: StructuralValidation) -> None:
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
                solution_method=candidate.solution_method,
                structural_validation=result,
            )
        )

    # Round 0: validate every first-attempt candidate in plan order.
    pending: list[_Pending] = []
    for candidate, item in zip(outcome.candidates, outcome.plan_items):
        result = validate(candidate)
        if result.passed:
            keep(candidate, result)
        else:
            pending.append(_Pending(candidate, item, result))

    # Rounds 1..N: feedback-driven regeneration, same contract as
    # /generate-and-verify - the exact rejection reasons go into the next prompt,
    # capped per variation. Every still-rejected variation is regenerated in the same
    # round, in waves of generation_concurrency, so retries parallelise like
    # first attempts do.
    can_regenerate = request.regenerate
    for attempt in range(1, settings.max_regeneration_attempts + 1):
        if not (can_regenerate and pending):
            break
        avoid = accepted + kept_texts
        for p in pending:
            p.history.append({"question": p.candidate.question, "reasons": p.result.reasons})

        def regenerate(p: _Pending, attempt: int = attempt) -> Candidate | None:
            return generation_engine.regenerate_one(
                seed,
                p.item,
                rejected_question=p.candidate.question,
                structural_reasons=p.result.reasons,
                reliability_reasons=[],
                flagged_spans=[],
                avoid_questions=avoid,
                difficulty_shift=request.difficulty_shift,
                attempt=attempt,
            )

        with watch.stage("ps8.regeneration"):
            with ThreadPoolExecutor(max_workers=max(1, settings.generation_concurrency)) as pool:
                futures = [pool.submit(regenerate, p) for p in pending]

        still_pending: list[_Pending] = []
        for p, future in zip(pending, futures):
            try:
                replacement = future.result()
            except OllamaUnavailable as exc:
                p.history.pop()  # this attempt never ran
                if can_regenerate:
                    warnings.append(f"Regeneration stopped at variation {p.item.index + 1}: {exc}")
                can_regenerate = False
                still_pending.append(p)
                continue
            regeneration_attempts += 1
            if replacement is None:
                warnings.append(
                    f"Regeneration attempt {attempt} for variation {p.item.index + 1} "
                    "produced unparseable output"
                )
                still_pending.append(p)
                continue
            p.candidate = replacement
            p.result = validate(replacement)
            if p.result.passed:
                keep(p.candidate, p.result)
                regenerated_accepted += 1
            else:
                still_pending.append(p)
        pending = still_pending

    for p in pending:
        rejected.append(
            {
                "question": p.candidate.question,
                "variation_strategy": p.candidate.variation_strategy,
                "reasons": p.result.reasons,
                "regeneration_attempts": len(p.history),
                "earlier_attempts": p.history,
            }
        )

    duplicate_rate = compute_duplicate_rate([v.question for v in variations])

    storage.audit(
        "ps8_generate",
        seed=request.seed_question[:200],
        domain=seed.domain,
        requested=request.count,
        accepted=len(variations),
        rejected=len(rejected),
        failed=len(outcome.failures),
        regeneration_attempts=regeneration_attempts,
        regenerated_accepted=regenerated_accepted,
        duplicate_rate=duplicate_rate,
    )

    missing = len(plan) - len(outcome.candidates)
    if missing:
        warnings.append(
            f"{missing} of {len(plan)} planned variations produced no usable "
            "candidate; see the warnings above for why."
        )

    return GenerateResponse(
        variations=variations,
        duplicate_rate=duplicate_rate,
        requested_count=request.count,
        generated_count=len(outcome.candidates),
        accepted_count=len(variations),
        rejected_count=len(rejected),
        regeneration_attempts=regeneration_attempts,
        regenerated_accepted=regenerated_accepted,
        seed_metadata=seed,
        rejected=rejected,
        timings_ms=watch.as_dict(),
        warnings=warnings,
    )
