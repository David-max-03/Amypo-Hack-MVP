"""Candidate Builder / JSON Parser (PS8).

A local 7B model does not reliably emit clean JSON, so this module is deliberately
forgiving. It recovers a candidate from:
  * clean JSON
  * JSON wrapped in ```json fences or surrounded by prose
  * JSON with trailing commas, single quotes, or Python literals (True/None)
  * truncated JSON whose closing braces were cut off by the token limit
  * a bare object nested under a wrapper key such as {"question": {...}}

Anything it had to repair is recorded in `parse_warnings` on the candidate, so the
UI and the audit log can show that the output needed fixing rather than hiding it.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from ..schemas import Candidate, SeedMetadata, TestCase, VariationPlanItem
from .seed_parser import DIFFICULTY_SCORES, estimate_difficulty, label_to_score

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)


def _strip_fences(text: str) -> tuple[str, bool]:
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip(), True
    return text.strip(), False


def _find_balanced_object(text: str) -> str | None:
    """Return the first brace-balanced JSON object, ignoring braces inside strings."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    # Unbalanced: the model was cut off. Close the open braces and try anyway.
    if depth > 0:
        return text[start:] + ("}" * depth)
    return None


def _repair(text: str) -> str:
    """Apply conservative fixes for the malformations a 7B model actually produces."""
    repaired = text
    # Trailing commas before a close.
    repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
    # Python literals.
    repaired = re.sub(r"\bTrue\b", "true", repaired)
    repaired = re.sub(r"\bFalse\b", "false", repaired)
    repaired = re.sub(r"\bNone\b", "null", repaired)
    # Unquoted keys: {question: "..."} -> {"question": "..."}
    repaired = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)", r'\1"\2"\3', repaired)
    # Literal newlines inside string values break json.loads; escape them.
    repaired = re.sub(
        r'"((?:[^"\\]|\\.)*)"',
        lambda m: '"' + m.group(1).replace("\n", "\\n").replace("\r", "") + '"',
        repaired,
        flags=re.S,
    )
    return repaired


def extract_json_object(raw: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Best-effort recovery of a JSON object from raw model output.

    Returns (parsed_or_None, warnings).
    """
    warnings: list[str] = []
    if not raw or not raw.strip():
        return None, ["model returned empty output"]

    text, fenced = _strip_fences(raw)
    if fenced:
        warnings.append("output was wrapped in markdown fences")

    # 1. Straight parse.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed, warnings
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            warnings.append("model returned a list; used the first object")
            return parsed[0], warnings
    except json.JSONDecodeError:
        pass

    # 2. Isolate the first balanced object, then parse.
    candidate_text = _find_balanced_object(text)
    if candidate_text is None:
        return None, warnings + ["no JSON object found in model output"]
    if not candidate_text.endswith("}") or candidate_text != text:
        warnings.append("extracted JSON object from surrounding text")

    try:
        parsed = json.loads(candidate_text)
        if isinstance(parsed, dict):
            return parsed, warnings
    except json.JSONDecodeError:
        pass

    # 3. Repair, then parse.
    try:
        parsed = json.loads(_repair(candidate_text))
        if isinstance(parsed, dict):
            warnings.append("malformed JSON was repaired before parsing")
            return parsed, warnings
    except json.JSONDecodeError as exc:
        return None, warnings + [f"JSON could not be repaired: {exc.msg}"]

    return None, warnings + ["parsed JSON was not an object"]


def _unwrap(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Unwrap {"variation": {...}} / {"result": {...}} style nesting."""
    if "question" in data and isinstance(data.get("question"), str):
        return data, []
    for key in ("variation", "result", "output", "data", "question", "candidate"):
        inner = data.get(key)
        if isinstance(inner, dict) and isinstance(inner.get("question"), str):
            return inner, [f"unwrapped nested object under {key!r}"]
    return data, []


def _as_text(value: Any) -> str:
    """Coerce a field to text. Models sometimes return a list or dict for a string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(_as_text(v) for v in value if v is not None).strip()
    if isinstance(value, dict):
        # e.g. {"explanation": "...", "code": "..."} -> join the values
        return "\n".join(f"{k}: {_as_text(v)}" for k, v in value.items()).strip()
    return str(value).strip()


def _parse_test_cases(value: Any) -> list[TestCase]:
    if not isinstance(value, list):
        return []
    out: list[TestCase] = []
    for item in value[:6]:
        if isinstance(item, dict):
            inp = _as_text(item.get("input", item.get("in", "")))
            exp = _as_text(
                item.get("expected_output", item.get("output", item.get("expected", "")))
            )
            if inp or exp:
                out.append(TestCase(input=inp, expected_output=exp))
        elif isinstance(item, str) and item.strip():
            out.append(TestCase(input=item.strip(), expected_output=""))
    return out


def build_candidate(
    raw_output: str,
    seed: SeedMetadata,
    plan: VariationPlanItem,
    *,
    attempt: int = 0,
    regenerated: bool = False,
    keep_raw: bool = True,
) -> Candidate | None:
    """Convert raw model output into a validated Candidate, or None if unusable.

    Missing non-essential fields are filled from the seed. A candidate is only
    rejected outright when it has no usable question text - everything else is
    recoverable and recorded as a warning.
    """
    parsed, warnings = extract_json_object(raw_output)
    if parsed is None:
        logger.warning("Unparseable model output for plan %s: %s", plan.index, warnings)
        return None

    parsed, unwrap_warnings = _unwrap(parsed)
    warnings.extend(unwrap_warnings)

    question = _as_text(parsed.get("question"))
    if not question or len(question) < 15:
        logger.warning("Candidate rejected: question text missing or too short")
        return None

    answer_key = _as_text(
        parsed.get("answer_key")
        or parsed.get("answer")
        or parsed.get("solution")
        or parsed.get("answerKey")
    )
    if not answer_key:
        # PS8 makes the answer key mandatory, so record the gap loudly rather than
        # silently shipping a question without one. Validation will fail it.
        warnings.append("model did not return an answer_key")

    # Difficulty: trust an explicit valid label, else re-estimate from the text.
    raw_difficulty = _as_text(parsed.get("difficulty")).lower()
    if raw_difficulty in DIFFICULTY_SCORES:
        difficulty = raw_difficulty
        difficulty_score = label_to_score(difficulty)
    else:
        if raw_difficulty:
            warnings.append(f"unrecognised difficulty {raw_difficulty!r}; re-estimated")
        difficulty, difficulty_score = estimate_difficulty(question)

    subtopic = _as_text(parsed.get("subtopic")) or None
    if subtopic and subtopic.lower() in {"null", "none", "n/a", ""}:
        subtopic = None

    return Candidate(
        id=f"q_{uuid.uuid4().hex[:10]}",
        question=question,
        answer_key=answer_key,
        domain=_as_text(parsed.get("domain")) or seed.domain,
        topic=_as_text(parsed.get("topic")) or seed.topic,
        subtopic=subtopic,
        difficulty=difficulty,  # type: ignore[arg-type]
        difficulty_score=difficulty_score,
        question_type=_as_text(parsed.get("question_type")) or seed.question_type,
        learning_objective=(
            _as_text(parsed.get("learning_objective")) or seed.learning_objective
        ),
        test_cases=_parse_test_cases(parsed.get("test_cases")),
        variation_strategy=plan.strategy,
        strategy_label=plan.strategy_label,
        attempt=attempt,
        regenerated=regenerated,
        raw_model_output=(raw_output[:4000] if keep_raw else None),
        parse_warnings=warnings,
    )
