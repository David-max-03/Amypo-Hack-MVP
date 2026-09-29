"""The integrated PS8 + PS2 pipeline.

    seed -> parse -> plan -> generate -> PS8 structural validation
                                      -> PS2 reliability verification
                                      -> decision -> PASS / REVIEW / REJECT
                                                        |
                                              REJECT -> regeneration (bounded)

Regeneration is feedback-driven, never blind: the exact PS8 failure reasons and PS2
flagged spans are written into the next prompt. Attempts are capped by
`settings.max_regeneration_attempts`; a candidate that still fails at the cap is
routed to REVIEW rather than looping forever or being silently dropped.
"""

from __future__ import annotations

import logging

from .config import settings
from .core import storage
from .core.ollama_client import OllamaUnavailable
from .core.timing import Stopwatch
from .decision.decision_engine import combined_feedback, decide
from .ps2 import engine as ps2_engine
from .ps8 import generation_engine, seed_parser, variation_planner
from .ps8.validation.engine import compute_duplicate_rate, validate_candidate
from .schemas import (
    Candidate,
    PipelineCandidate,
    PipelineSummary,
    SeedMetadata,
    VariationPlanItem,
)

logger = logging.getLogger(__name__)


def _evaluate(
    candidate: Candidate,
    seed: SeedMetadata,
    *,
    generated_so_far: list[str],
    accepted_texts: list[str],
    difficulty_shift: str | None,
    verify: bool,
):
    """Run both gates on one candidate and return (decision, structural, reliability)."""
    structural = validate_candidate(
        candidate,
        seed,
        previously_generated=generated_so_far,
        previously_accepted=accepted_texts,
        difficulty_shift=difficulty_shift,
    )

    # Skip PS2 when the candidate already failed PS8 - verifying a known-bad
    # candidate wastes seconds we owe to the latency budget.
    reliability = None
    if verify and structural.passed:
        reliability = ps2_engine.verify_candidate(candidate)

    result = decide(structural, reliability)
    return result, structural, reliability


def run_pipeline(
    seed_question: str,
    domain: str,
    count: int,
    *,
    difficulty_shift: str | None = None,
    enable_regeneration: bool = True,
    verify: bool = True,
    persist: bool = True,
    use_llm_parser: bool = True,
) -> tuple[SeedMetadata, list[PipelineCandidate], PipelineSummary, dict[str, float], list[str]]:
    """Execute the full integrated pipeline for one seed question."""
    watch = Stopwatch()
    warnings: list[str] = []

    # ---- Step 1-2: parse the seed -----------------------------------
    with watch.stage("ps8.seed_parsing"):
        seed = seed_parser.parse_seed(seed_question, domain, use_llm=use_llm_parser)

    # ---- Step 3: plan the variations --------------------------------
    with watch.stage("ps8.variation_planning"):
        plan = variation_planner.plan_variations(
            seed, count, difficulty_shift=difficulty_shift
        )

    accepted_texts = storage.accepted_question_texts() if persist else []
    generated_texts: list[str] = []
    results: list[PipelineCandidate] = []
    regeneration_attempts = 0

    # ---- Step 4-9: generate, validate, verify, decide ---------------
    for item in plan:
        parse_errors: list[str] = []
        try:
            with watch.stage("ps8.generation"):
                candidate = generation_engine.generate_one(
                    seed,
                    item,
                    avoid_questions=accepted_texts + generated_texts,
                    difficulty_shift=difficulty_shift,
                    errors=parse_errors,
                )
        except OllamaUnavailable as exc:
            warnings.append(f"Generation stopped at variation {item.index + 1}: {exc}")
            logger.error("Pipeline aborted: %s", exc)
            break

        if candidate is None:
            warnings.append(
                f"Variation {item.index + 1} ({item.strategy}): model output could not "
                f"be parsed into a candidate after {len(parse_errors)} attempt(s)"
                + (f" - {parse_errors[-1]}" if parse_errors else "")
            )
            continue

        with watch.stage("pipeline.evaluation"):
            result, structural, reliability = _evaluate(
                candidate,
                seed,
                generated_so_far=generated_texts,
                accepted_texts=accepted_texts,
                difficulty_shift=difficulty_shift,
                verify=verify,
            )

        history: list[dict] = []
        attempts = 1

        # ---- Step 10: bounded, feedback-driven regeneration ---------
        while (
            enable_regeneration
            and result.decision == "REJECT"
            and attempts <= settings.max_regeneration_attempts
        ):
            s_reasons, r_reasons, spans = combined_feedback(structural, reliability)
            history.append(
                {
                    "attempt": attempts,
                    "rejected_question": candidate.question,
                    "decision": result.decision,
                    "structural_reasons": s_reasons,
                    "reliability_reasons": r_reasons,
                    "flagged_spans": spans,
                }
            )

            logger.info(
                "Regenerating variation %s (attempt %s/%s): %s",
                item.index + 1,
                attempts,
                settings.max_regeneration_attempts,
                "; ".join(s_reasons[:2] + r_reasons[:1]) or "no reason recorded",
            )

            try:
                with watch.stage("ps8.regeneration"):
                    replacement = generation_engine.regenerate_one(
                        seed,
                        item,
                        rejected_question=candidate.question,
                        structural_reasons=s_reasons,
                        reliability_reasons=r_reasons,
                        flagged_spans=spans,
                        avoid_questions=accepted_texts + generated_texts,
                        difficulty_shift=difficulty_shift,
                        attempt=attempts,
                    )
            except OllamaUnavailable as exc:
                warnings.append(f"Regeneration failed for variation {item.index + 1}: {exc}")
                break

            regeneration_attempts += 1
            attempts += 1

            if replacement is None:
                warnings.append(
                    f"Regeneration attempt {attempts - 1} for variation "
                    f"{item.index + 1} produced unparseable output"
                )
                continue

            candidate = replacement
            with watch.stage("pipeline.evaluation"):
                result, structural, reliability = _evaluate(
                    candidate,
                    seed,
                    generated_so_far=generated_texts,
                    accepted_texts=accepted_texts,
                    difficulty_shift=difficulty_shift,
                    verify=verify,
                )

        # Hit the cap and still failing: a human decides, we do not discard silently.
        decision = result.decision
        extra_reasons = list(result.reasons)
        if (
            decision == "REJECT"
            and enable_regeneration
            and attempts > settings.max_regeneration_attempts
        ):
            decision = "REVIEW"
            extra_reasons.append(
                f"REVIEW: reached the maximum of {settings.max_regeneration_attempts} "
                "regeneration attempts without passing both gates - routed to human "
                "review instead of being discarded"
            )

        status = {
            "PASS": "accepted",
            "REVIEW": "review",
            "REJECT": "rejected",
        }[decision]

        pipeline_candidate = PipelineCandidate(
            candidate=candidate,
            decision=decision,  # type: ignore[arg-type]
            decision_reasons=extra_reasons,
            structural_validation=structural,
            reliability_verification=reliability,
            status=status,  # type: ignore[arg-type]
            attempts=attempts,
            regeneration_history=history,
        )
        results.append(pipeline_candidate)

        # Only accepted questions become duplicate-detection memory for this run;
        # a rejected candidate should not block a later good one.
        if decision == "PASS":
            generated_texts.append(candidate.question)

        # ---- Step 11: persist ---------------------------------------
        if persist:
            _persist(pipeline_candidate, seed)

    # ---- Summary ----------------------------------------------------
    with watch.stage("pipeline.summary"):
        summary = _summarise(results, requested=count, regeneration_attempts=regeneration_attempts)

    if persist:
        storage.audit(
            "pipeline_run",
            seed=seed_question[:200],
            domain=seed.domain,
            requested=count,
            passed=summary.passed,
            review=summary.review,
            rejected=summary.rejected,
            regeneration_attempts=regeneration_attempts,
        )

    return seed, results, summary, watch.as_dict(), warnings


def _persist(item: PipelineCandidate, seed: SeedMetadata) -> None:
    """Write one evaluated candidate to the appropriate local JSON store."""
    record = {
        "id": item.candidate.id,
        "question": item.candidate.question,
        "answer_key": item.candidate.answer_key,
        "domain": item.candidate.domain,
        "topic": item.candidate.topic,
        "subtopic": item.candidate.subtopic,
        "difficulty": item.candidate.difficulty,
        "difficulty_score": item.candidate.difficulty_score,
        "question_type": item.candidate.question_type,
        "learning_objective": item.candidate.learning_objective,
        "test_cases": [tc.model_dump() for tc in item.candidate.test_cases],
        "variation_strategy": item.candidate.variation_strategy,
        "seed_question": seed.raw_seed,
        "decision": item.decision,
        "attempts": item.attempts,
        "created_at": storage.utc_now(),
    }

    if item.reliability_verification is not None:
        record["reliability_score"] = item.reliability_verification.reliability_score
        record["verdict"] = item.reliability_verification.verdict
        record["hallucination_probability"] = (
            item.reliability_verification.hallucination_probability
        )

    if item.decision == "PASS":
        storage.save_accepted_question(record)
    elif item.decision == "REVIEW":
        storage.save_review_item(
            {
                **record,
                "review_reasons": item.decision_reasons,
                "flagged_spans": (
                    [s.model_dump() for s in item.reliability_verification.flagged_spans]
                    if item.reliability_verification
                    else []
                ),
            }
        )

    storage.save_validation_report(
        {
            "candidate_id": item.candidate.id,
            "question": item.candidate.question[:400],
            "decision": item.decision,
            "attempts": item.attempts,
            "structural_validation": (
                item.structural_validation.model_dump() if item.structural_validation else None
            ),
            "reliability_verification": (
                item.reliability_verification.model_dump()
                if item.reliability_verification
                else None
            ),
            "created_at": storage.utc_now(),
        }
    )


def _summarise(
    results: list[PipelineCandidate], *, requested: int, regeneration_attempts: int
) -> PipelineSummary:
    passed = sum(1 for r in results if r.decision == "PASS")
    review = sum(1 for r in results if r.decision == "REVIEW")
    rejected = sum(1 for r in results if r.decision == "REJECT")

    scores = [
        r.reliability_verification.reliability_score
        for r in results
        if r.reliability_verification is not None
    ]
    flagged = sum(
        len(r.reliability_verification.flagged_spans)
        for r in results
        if r.reliability_verification is not None
    )

    # Duplicate rate is measured over what we would actually ship.
    shipped = [r.candidate.question for r in results if r.decision in {"PASS", "REVIEW"}]

    return PipelineSummary(
        requested=requested,
        generated=len(results),
        passed=passed,
        review=review,
        rejected=rejected,
        duplicate_rate=compute_duplicate_rate(shipped),
        regeneration_attempts=regeneration_attempts,
        mean_reliability_score=round(sum(scores) / len(scores), 4) if scores else 0.0,
        flagged_span_count=flagged,
    )
