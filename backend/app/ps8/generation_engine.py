"""AI Generation Engine (PS8).

Drives Ollama + Qwen2.5-Coder 7B to turn a variation plan into candidates. Generation
runs in waves of `settings.generation_concurrency` requests. The default of 1 is
sequential, because an Ollama instance without OLLAMA_NUM_PARALLEL queues concurrent
requests (measured: 4 at once took exactly 4x as long). Raise both together.

A failed or unparseable generation never aborts the batch - it is recorded and the
run continues, because PS8 is scored on how many valid variations come out.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..config import settings
from ..core.ollama_client import OllamaUnavailable, ollama
from ..schemas import Candidate, SeedMetadata, VariationPlanItem
from . import prompt_builder
from .candidate_builder import build_candidate, parse_candidate

logger = logging.getLogger(__name__)


@dataclass
class GenerationOutcome:
    """Result of attempting the whole plan."""

    candidates: list[Candidate] = field(default_factory=list)
    # plan_items[i] is the plan entry candidates[i] was generated from, so a caller
    # can regenerate a rejected candidate against the same strategy.
    plan_items: list[VariationPlanItem] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def generate_one(
    seed: SeedMetadata,
    plan: VariationPlanItem,
    *,
    avoid_questions: list[str] | None = None,
    difficulty_shift: str | None = None,
    attempt: int = 0,
    errors: list[str] | None = None,
    client=None,
) -> Candidate | None:
    """Generate a single candidate for one planned variation.

    Unparseable output is retried up to `settings.parse_retry_attempts` times. Each
    failed parse's reason is appended to `errors` (when given) so callers can report
    exactly why a variation was dropped instead of losing it silently.
    """
    llm = client or ollama  # `client` is only overridden by Demo Mode's scripted replay
    prompt = prompt_builder.build_generation_prompt(
        seed,
        plan,
        avoid_questions=avoid_questions,
        difficulty_shift=difficulty_shift,
    )
    for parse_try in range(settings.parse_retry_attempts + 1):
        if parse_try == 0:
            raw = llm.generate(prompt, system=prompt_builder.SYSTEM_PROMPT)
        else:
            raw = llm.generate(
                prompt,
                system=prompt_builder.SYSTEM_PROMPT,
                temperature=settings.regeneration_temperature,
                max_tokens=settings.parse_retry_max_tokens,
            )
        candidate, reason = parse_candidate(raw, seed, plan, attempt=attempt)
        if candidate is not None:
            if parse_try:
                candidate.parse_warnings.append(
                    f"first output was unparseable; succeeded on retry {parse_try}"
                )
            return candidate
        logger.warning(
            "Plan %s parse attempt %s failed: %s", plan.index, parse_try + 1, reason
        )
        if errors is not None:
            errors.append(f"parse attempt {parse_try + 1}: {reason}")
    return None


def regenerate_one(
    seed: SeedMetadata,
    plan: VariationPlanItem,
    *,
    rejected_question: str,
    structural_reasons: list[str],
    reliability_reasons: list[str],
    flagged_spans: list[dict],
    avoid_questions: list[str] | None = None,
    difficulty_shift: str | None = None,
    attempt: int = 1,
    client=None,
) -> Candidate | None:
    """Generate a replacement candidate from combined PS8 + PS2 rejection feedback."""
    prompt = prompt_builder.build_regeneration_prompt(
        seed,
        plan,
        rejected_question=rejected_question,
        structural_reasons=structural_reasons,
        reliability_reasons=reliability_reasons,
        flagged_spans=flagged_spans,
        avoid_questions=avoid_questions,
        difficulty_shift=difficulty_shift,
    )
    raw = (client or ollama).generate(
        prompt,
        system=prompt_builder.SYSTEM_PROMPT,
        temperature=settings.regeneration_temperature,
    )
    return build_candidate(raw, seed, plan, attempt=attempt, regenerated=True)


def generate_batch(
    seed: SeedMetadata,
    plan: list[VariationPlanItem],
    *,
    difficulty_shift: str | None = None,
    known_questions: list[str] | None = None,
    on_progress=None,
) -> GenerationOutcome:
    """Run the whole plan in waves of `settings.generation_concurrency` requests.

    Each wave's prompts list every question generated in earlier waves - the cheapest
    duplicate-suppression we have, stopping the model repeating itself before the
    duplicate validator has to reject anything. With concurrency 1 every wave is a
    single request, which is the fully sequential behaviour.
    """
    outcome = GenerationOutcome()
    avoid: list[str] = list(known_questions or [])
    wave_size = max(1, settings.generation_concurrency)

    with ThreadPoolExecutor(max_workers=wave_size) as pool:
        for start in range(0, len(plan), wave_size):
            wave = plan[start : start + wave_size]
            snapshot = list(avoid)
            errors: list[list[str]] = [[] for _ in wave]
            futures = [
                pool.submit(
                    generate_one,
                    seed,
                    item,
                    avoid_questions=snapshot,
                    difficulty_shift=difficulty_shift,
                    errors=errs,
                )
                for item, errs in zip(wave, errors)
            ]

            outage: OllamaUnavailable | None = None
            for item, errs, future in zip(wave, errors, futures):
                try:
                    candidate = future.result()
                except OllamaUnavailable as exc:
                    outage = outage or exc
                    outcome.failures.append(
                        {"index": item.index, "strategy": item.strategy, "error": str(exc)}
                    )
                    continue

                if candidate is None:
                    outcome.failures.append(
                        {
                            "index": item.index,
                            "strategy": item.strategy,
                            "error": "model output could not be parsed into a candidate",
                            "attempts": errs,
                        }
                    )
                    outcome.warnings.append(
                        f"Variation {item.index + 1} ({item.strategy}) dropped after "
                        f"{len(errs)} unparseable output(s): {errs[-1] if errs else 'no reason'}"
                    )
                    logger.warning("Plan %s produced unparseable output", item.index)
                    continue

                outcome.candidates.append(candidate)
                outcome.plan_items.append(item)
                avoid.append(candidate.question)
                if on_progress is not None:
                    on_progress(candidate, item)

            if outage is not None:
                # The runtime is down. Nothing later in the batch can succeed either.
                logger.error("Generation aborted in wave starting at plan %s: %s", start, outage)
                unattempted = len(plan) - (start + len(wave))
                outcome.warnings.append(
                    f"Generation stopped early at variation {start + 1}: {outage}"
                    + (
                        f" ({unattempted} later variations were never attempted)"
                        if unattempted
                        else ""
                    )
                )
                break

    if not outcome.candidates and not outcome.warnings:
        outcome.warnings.append("No candidate could be parsed from any generation attempt.")
    return outcome
