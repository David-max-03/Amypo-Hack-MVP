"""Prompt Builder (PS8).

Turns the seed contract + a chosen variation strategy + (on a retry) the combined
PS8/PS2 rejection feedback into one structured generation prompt.

The model is never told just to "generate a variation". It is given a contract: the
seed, what the seed assesses, what is immutable, the one dimension the current
strategy varies, what it may change and what it must not. Nothing in the prompt
names a topic of its own - every example is phrased in terms of the seed - so the
prompt cannot pull a question towards an unrelated subject.

The regeneration path is the important one: we never ask the model to "try again".
We tell it exactly which checks failed and what to change, which is what makes the
loop converge instead of producing the same rejected candidate twice.
"""

from __future__ import annotations

from ..schemas import SeedMetadata, VariationPlanItem
from . import strategies
from .contract import get_contract

SYSTEM_PROMPT = (
    "You are an expert assessment author who writes original exam questions. "
    "You always return a single valid JSON object and nothing else - no prose, no "
    "markdown fences, no commentary. Every question you write must be solvable and "
    "must ship with a correct, complete answer key."
)

# Only fields the model has to invent. Domain, topic, question type, subtopic and
# learning objective are filled from the seed by the candidate builder: asking the
# model to echo them back cost ~40% of every generation's output tokens.
_JSON_SHAPE = """{
  "question": "the full question text, self-contained and solvable",
  "answer_key": "__ANSWER__",
  "difficulty": "easy | medium | hard",
  "test_cases": [{"input": "...", "expected_output": "..."}]
}"""


def _is_coding(seed: SeedMetadata) -> bool:
    return seed.question_type == "coding"


# What the JSON template shows in place of the answer key. A weak model sometimes
# returns the hint itself as its answer; the validator rejects that by comparing
# against these exact strings.
ANSWER_HINTS = {
    "coding": "complete runnable reference solution code, then a one-sentence explanation",
    "other": "the final answer stated explicitly, then the working that justifies it",
}


def _json_shape(seed: SeedMetadata) -> str:
    answer_hint = ANSWER_HINTS["coding" if _is_coding(seed) else "other"]
    return _JSON_SHAPE.replace("__ANSWER__", answer_hint)


def _json_shape_for(seed: SeedMetadata, target_difficulty: str) -> str:
    """The JSON template, listing "expert" only when Expert was explicitly requested -
    every other prompt stays identical to before."""
    shape = _json_shape(seed)
    if target_difficulty == "expert":
        shape = shape.replace('"easy | medium | hard"', '"easy | medium | hard | expert"')
    return shape


def _answer_key_clause(seed: SeedMetadata) -> str:
    """The answer key must be usable for marking, not a description of an answer."""
    if _is_coding(seed):
        return (
            "The answer_key MUST contain a complete, runnable reference solution as code "
            "- the full function, query or markup the question asks for - in the "
            "language or technology the question names, or Python if none is named. Do "
            "NOT describe what the solution should do - write it. Put tests in "
            "test_cases, not in the answer_key. Encode newlines inside the JSON string "
            "as \\n."
        )
    return (
        "The answer_key MUST state the final answer explicitly, followed by the working. "
        "Do NOT describe what a good answer would contain - give the answer."
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

    method_block = (
        f"\nREQUIRED SOLUTION METHOD - {plan.method_label}:\n{plan.method_instruction}\n"
        if plan.method
        else ""
    )

    test_case_clause = (
        "Include exactly 2 short test cases with exact inputs and expected outputs."
        if seed.question_type == "coding"
        else "Leave test_cases as an empty list unless concrete examples genuinely help."
    )

    contract = get_contract(seed)
    immutable = [
        f"It assesses the same core learning objective: {contract.learning_objective}",
        f"It asks the learner to do what the seed asks ({contract.task_type}), in the "
        f"same domain ({contract.domain}).",
    ]
    if contract.required_elements:
        immutable.append(
            "It is still explicitly about: " + ", ".join(contract.required_elements) + "."
        )
    if contract.named_elements:
        immutable.append(
            "It keeps the technology / named concept of the seed: "
            + ", ".join(contract.named_elements) + "."
        )
    if contract.structure_anchor:
        immutable.append(f"It still operates on a {contract.structure_anchor}.")
    if contract.constraints and plan.strategy != "constraint":
        immutable.append(
            "It keeps the seed's stated constraints: " + "; ".join(contract.constraints) + "."
        )
    immutable_block = "\n".join(f"  - {line}" for line in immutable)
    prohibited = plan.must_not_change or [
        "the core learning objective", "the task the learner performs", "the domain",
    ]
    dimension = f" (it varies {plan.dimension})" if plan.dimension else ""
    # The first words of the seed, quoted so the model can be told not to reuse them.
    seed_opening = " ".join(seed.raw_seed.split()[:6])
    opening = strategies.STRATEGIES[plan.strategy].opening if plan.strategy in strategies.STRATEGIES else ""

    return f"""Write ONE new exam question that is a controlled variation of the seed below.

ORIGINAL SEED:
{seed.raw_seed}

SEED CONTRACT - what the seed assesses:
  domain                  : {contract.domain}
  topic                   : {seed.topic}
  core concept            : {contract.core_concept}
  task type               : {contract.task_type}
  difficulty              : {seed.difficulty}
  core learning objective : {contract.learning_objective}

IMMUTABLE - all of this must still be true of your question:
{immutable_block}

CURRENT VARIATION STRATEGY - {plan.strategy_label}{dimension}:
{plan.instruction}

YOU MAY CHANGE:      {', '.join(plan.change)}
YOU MUST PRESERVE:   {', '.join(plan.preserve)}
YOU MUST NOT CHANGE: {'; '.join(prohibited)}
{method_block}
HOW TO WRITE IT - a question that repeats the seed's sentence and adds to it is rejected:
  - {opening}
  - Do not begin with "{seed_opening}" and do not reuse the seed's sentence anywhere.
  - Give the question specifics of its own: named things, example values or inputs.
    Wording, names and example values are always free to change.
  - Write at least two sentences, and put the request to the learner last.

RULES:
  1. {difficulty_clause}
  2. The new question must assess the SAME core concept: {contract.core_concept}.
     Do NOT replace the seed's subject with a different topic, algorithm, data
     structure, technology or task. A question about something else is wrong
     however well it is written.
  3. It must NOT be a paraphrase or reworded copy of the seed. Make the change this
     strategy asks for clearly visible, and change nothing the contract forbids.
  4. The question must be fully self-contained and solvable on its own.
  5. The answer_key must be correct for YOUR question, not for the seed.
  6. {_answer_key_clause(seed)}
  7. {test_case_clause}
  8. State only facts you are confident are true. Do not invent statistics,
     citations, standards, library functions or historical details.
{avoid_block}
Return ONLY this JSON object:
{_json_shape_for(seed, target_difficulty)}"""


def failure_instructions(
    seed: SeedMetadata,
    plan: VariationPlanItem,
    structural_reasons: list[str],
    reliability_reasons: list[str],
    *,
    difficulty_shift: str | None = None,
) -> list[str]:
    """One targeted instruction per kind of failure - never a generic "try again".

    Each validator's reason starts with a fixed phrase naming the check that failed,
    so the failure is identified by that phrase rather than by loose keyword search
    (a concept-drift reason mentions "similarity" too, and must not be answered with
    "change more").
    """
    contract = get_contract(seed)
    structural = [r.lower() for r in structural_reasons]
    reliability = " ".join(reliability_reasons).lower()

    def failed(*prefixes: str) -> bool:
        return any(r.startswith(p) for r in structural for p in prefixes)

    subject = ", ".join(contract.required_elements + contract.named_elements) or contract.core_concept
    opening = strategies.STRATEGIES[plan.strategy].opening if plan.strategy in strategies.STRATEGIES else ""
    keep = (
        f"Preserve the original learning objective ({contract.learning_objective}) and keep "
        f"the question explicitly about {subject}."
    )
    fixes: list[str] = []

    if failed("learning objective changed", "concept not preserved", "domain drifted"):
        fixes.append(
            "The previous candidate changed the underlying task - it was about something "
            f"other than what the seed assesses. {keep} Then apply the requested "
            f"strategy ({plan.strategy_label}) to THAT task, not to a different one."
        )
    if failed("variation drifted too far"):
        fixes.append(
            f"The previous candidate moved too far from the seed. {keep} Vary only "
            f"{plan.dimension or 'the dimension this strategy names'}."
        )
    if failed("semantic similarity too high", "lexical similarity too high",
              "not a meaningful variation"):
        fixes.append(
            "The previous candidate was too close to an existing question - it repeated "
            "that question's sentence and only added to it. Preserve the core learning "
            "objective, but produce a more meaningfully different variation using the "
            f"requested strategy: change {', '.join(plan.change)} much more visibly. "
            f"{opening} Do not start the way the seed or the rejected question starts; "
            "restate the task in entirely different words, with new concrete specifics, "
            f"while keeping it explicitly about {subject}."
        )
    if failed("strategy not followed"):
        fixes.append(
            f"The previous candidate did not apply the requested strategy. {plan.instruction}"
        )
    if failed("difficulty mismatch"):
        target = difficulty_shift or seed.difficulty
        direction = ""
        joined = " ".join(structural)
        if "harder than" in joined:
            direction = " The previous candidate was too hard: remove steps, conditions or constraints."
        elif "easier than" in joined:
            direction = " The previous candidate was too easy: add steps, conditions or constraints."
        fixes.append(
            "Preserve the learning objective and the concept while adjusting the complexity "
            f"to the requested difficulty, '{target}'.{direction}"
        )
    if failed("answer key describes a solution", "answer key is too short", "missing answer key"):
        fixes.append(_answer_key_clause(seed))
    if failed("solution method") and plan.method:
        fixes.append(plan.method_instruction)

    if "unsupported" in reliability or "hallucinat" in reliability or "fabricat" in reliability \
            or "could not be grounded" in reliability:
        fixes.append(
            "Remove every claim you cannot be certain is true. Do not cite sources, "
            "statistics, standards or named results. Keep the question self-contained."
        )
    if "contradict" in reliability:
        fixes.append(
            "Make the question and the answer key mutually consistent - the rejected "
            "attempt contradicted itself or an established fact."
        )
    return fixes


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

    fixes = failure_instructions(
        seed, plan, structural_reasons, reliability_reasons, difficulty_shift=difficulty_shift
    )

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
