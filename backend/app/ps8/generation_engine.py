"""AI Generation Engine (PS8).

Drives Ollama + Qwen2.5-Coder 7B to turn a variation plan into candidates. Generation
is sequential: a local 7B model on CPU/Metal is the bottleneck, and firing parallel
requests at one Ollama instance makes total latency worse, not better.

A failed or unparseable generation never aborts the batch - it is recorded and the
run continues, because PS8 is scored on how many valid variations come out.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..config import settings
from ..core.ollama_client import OllamaUnavailable, ollama
from ..schemas import Candidate, SeedMetadata, VariationPlanItem
from . import prompt_builder
from .candidate_builder import build_candidate

logger = logging.getLogger(__name__)


@dataclass
class GenerationOutcome:
    """Result of attempting the whole plan."""

    candidates: list[Candidate] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def generate_one(
    seed: SeedMetadata,
    plan: VariationPlanItem,
    *,
    avoid_questions: list[str] | None = None,
    difficulty_shift: str | None = None,
    attempt: int = 0,
) -> Candidate | None:
    """Generate a single candidate for one planned variation."""
    prompt = prompt_builder.build_generation_prompt(
        seed,
        plan,
        avoid_questions=avoid_questions,
        difficulty_shift=difficulty_shift,
    )
    raw = ollama.generate(prompt, system=prompt_builder.SYSTEM_PROMPT)
    return build_candidate(raw, seed, plan, attempt=attempt)


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
    raw = ollama.generate(
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
    """Run the whole plan, feeding each new question back as context for the next.

    Passing already-generated questions into the next prompt is the cheapest
    duplicate-suppression we have: it stops the model repeating itself before the
    duplicate validator ever has to reject anything.
    """
    outcome = GenerationOutcome()
    avoid: list[str] = list(known_questions or [])

    for item in plan:
        try:
            candidate = generate_one(
                seed,
                item,
                avoid_questions=avoid,
                difficulty_shift=difficulty_shift,
            )
        except OllamaUnavailable as exc:
            # The runtime is down. Nothing later in the batch can succeed either.
            logger.error("Generation aborted at plan %s: %s", item.index, exc)
            outcome.failures.append(
                {"index": item.index, "strategy": item.strategy, "error": str(exc)}
            )
            outcome.warnings.append(f"Generation stopped early: {exc}")
            break

        if candidate is None:
            outcome.failures.append(
                {
                    "index": item.index,
                    "strategy": item.strategy,
                    "error": "model output could not be parsed into a candidate",
                }
            )
            logger.warning("Plan %s produced unparseable output", item.index)
            continue

        outcome.candidates.append(candidate)
        avoid.append(candidate.question)
        if on_progress is not None:
            on_progress(candidate, item)

    if not outcome.candidates and not outcome.warnings:
        outcome.warnings.append("No candidate could be parsed from any generation attempt.")
    return outcome
