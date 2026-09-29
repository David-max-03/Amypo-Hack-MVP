"""Prompt Builder (PS8).

Turns seed metadata + a chosen variation strategy + (on a retry) the combined
PS8/PS2 rejection feedback into one structured generation prompt.

The regeneration path is the important one: we never ask the model to "try again".
We tell it exactly which checks failed and what to change, which is what makes the
loop converge instead of producing the same rejected candidate twice.
"""

from __future__ import annotations

from ..schemas import SeedMetadata, VariationPlanItem

SYSTEM_PROMPT = (
    "You are an expert assessment author who writes original exam questions. "
    "You always return a single valid JSON object and nothing else - no prose, no "
    "markdown fences, no commentary. Every question you write must be solvable and "
    "must ship with a correct, complete answer key."
)

_JSON_SHAPE = """{
  "question": "the full question text, self-contained and solvable",
  "answer_key": "the complete correct answer, including the reasoning or working",
  "domain": "__DOMAIN__",
  "topic": "__TOPIC__",
  "subtopic": "a more specific subtopic or null",
  "difficulty": "easy | medium | hard",
  "question_type": "__QTYPE__",
  "learning_objective": "what the learner demonstrates by answering correctly",
  "test_cases": [{"input": "...", "expected_output": "..."}]
}"""


def _json_shape(seed: SeedMetadata) -> str:
    return (
        _JSON_SHAPE.replace("__DOMAIN__", seed.domain)
        .replace("__TOPIC__", seed.topic)
        .replace("__QTYPE__", seed.question_type)
    )


def build_generation_prompt(
    seed: SeedMetadata,
    plan: VariationPlanItem,
    *,
    avoid_questions: list[str] | None = None,
    difficulty_shift: str | None = None,
) -> str:
    """Build the first-attempt prompt for one planned variation."""
    target_difficulty = difficulty_shift or seed.difficulty
    difficulty_clause = (
        f"The difficulty MUST be '{target_difficulty}'."
        if difficulty_shift
        else (
            f"The difficulty MUST stay equivalent to the seed: '{seed.difficulty}'. "
            "Do not make it noticeably easier or harder."
        )
    )

    avoid_block = ""
    if avoid_questions:
        # Only the most recent few - a huge block wastes context and confuses a 7B model.
        recent = avoid_questions[-6:]
        listed = "\n".join(f"  - {q}" for q in recent)
        avoid_block = (
            "\nALREADY-GENERATED QUESTIONS (yours must be clearly different from every "
            f"one of these):\n{listed}\n"
        )

    test_case_clause = (
        "Include 2-3 concrete test cases with exact inputs and expected outputs."
        if seed.question_type == "coding"
        else "Leave test_cases as an empty list unless concrete examples genuinely help."
    )

    return f"""Write ONE new exam question that is a controlled variation of the seed below.

SEED QUESTION:
{seed.raw_seed}

SEED ANALYSIS:
  domain             : {seed.domain}
  topic              : {seed.topic}
  core concept       : {seed.core_concept}
  question type      : {seed.question_type}
  difficulty         : {seed.difficulty}
  learning objective : {seed.learning_objective}

VARIATION STRATEGY - {plan.strategy_label}:
{plan.instruction}

YOU MUST PRESERVE: {', '.join(plan.preserve)}
YOU MUST CHANGE:   {', '.join(plan.change)}

RULES:
  1. {difficulty_clause}
  2. The new question must assess the SAME core concept: {seed.core_concept}.
  3. It must NOT be a paraphrase or reworded copy of the seed. Change the surface
     content substantially - new scenario, new entities, new numbers where relevant.
  4. The question must be fully self-contained and solvable on its own.
  5. The answer_key must be correct for YOUR question, not for the seed.
  6. {test_case_clause}
  7. State only facts you are confident are true. Do not invent statistics,
     citations, standards, library functions or historical details.
{avoid_block}
Return ONLY this JSON object:
{_json_shape(seed)}"""


def build_regeneration_prompt(
    seed: SeedMetadata,
    plan: VariationPlanItem,
    *,
    rejected_question: str,
    structural_reasons: list[str],
    reliability_reasons: list[str],
    flagged_spans: list[dict],
    avoid_questions: list[str] | None = None,
    difficulty_shift: str | None = None,
) -> str:
    """Build a corrective prompt from the combined PS8 + PS2 rejection feedback."""
    base = build_generation_prompt(
        seed, plan, avoid_questions=avoid_questions, difficulty_shift=difficulty_shift
    )

    problems: list[str] = []
    for reason in structural_reasons:
        problems.append(f"  [PS8 structural] {reason}")
    for reason in reliability_reasons:
        problems.append(f"  [PS2 reliability] {reason}")
    for span in flagged_spans[:5]:
        text = str(span.get("text", ""))[:160]
        why = str(span.get("reason", ""))
        problems.append(f'  [PS2 flagged span] "{text}" -> {why}')

    problem_block = "\n".join(problems) if problems else "  (no specific reason recorded)"

    # Targeted, check-specific instructions beat a generic "do better".
    fixes: list[str] = []
    joined = " ".join(structural_reasons + reliability_reasons).lower()
    if "duplicate" in joined or "similar" in joined or "paraphrase" in joined:
        fixes.append(
            "Change the scenario, entities and numbers far more aggressively. The new "
            "question should share almost no wording with the rejected one."
        )
    if "difficulty" in joined:
        fixes.append(
            f"Recalibrate the difficulty to '{difficulty_shift or seed.difficulty}' - adjust "
            "the number of steps and constraints required to solve it."
        )
    if "concept" in joined:
        fixes.append(
            f"Stay on the seed's core concept: {seed.core_concept}. The rejected attempt "
            "drifted to a different topic."
        )
    if "unsupported" in joined or "hallucinat" in joined or "fabricat" in joined:
        fixes.append(
            "Remove every claim you cannot be certain is true. Do not cite sources, "
            "statistics, standards or named results. Keep the question self-contained."
        )
    if "contradict" in joined:
        fixes.append(
            "Make the question and the answer key mutually consistent - the rejected "
            "attempt contradicted itself."
        )
    if "answer" in joined and "incomplete" in joined:
        fixes.append("Write a complete answer key that fully solves the question.")

    fix_block = "\n".join(f"  - {f}" for f in fixes) or "  - Address every problem listed above."

    return f"""{base}

================= REGENERATION - PREVIOUS ATTEMPT WAS REJECTED =================

REJECTED QUESTION:
{rejected_question}

WHY IT WAS REJECTED:
{problem_block}

WHAT YOU MUST DO DIFFERENTLY:
{fix_block}

Write a NEW question that fixes every problem above. Return ONLY the JSON object."""
