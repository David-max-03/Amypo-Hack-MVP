"""Seed Parser (PS8).

Extracts the structured metadata a variation must preserve: domain, topic, subtopic,
core concept, question type, difficulty and learning objective.

Two paths:
  * `parse_seed(..., use_llm=True)` asks Qwen2.5-Coder via Ollama and keeps any field
    it returns that looks sane, falling back field-by-field to the heuristic.
  * the heuristic path is pure Python, deterministic and always available, so the
    system still parses seeds when Ollama is down and unit tests never need a model.
"""

from __future__ import annotations

import logging
import re

from ..core.ollama_client import OllamaUnavailable, ollama
from ..core.text_utils import content_tokens, normalize
from ..schemas import SeedMetadata
from . import domains

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Question-type detection
# ----------------------------------------------------------------------
_TYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("mcq", re.compile(r"\b(which of the following|choose the correct|select the (?:correct|best)|options?\s*[:\-])", re.I)),
    ("fill_in_the_blank", re.compile(r"(_{3,}|\bfill in the blanks?\b)", re.I)),
    ("true_false", re.compile(r"\b(true or false|state whether.*true)\b", re.I)),
    ("coding", re.compile(r"\b(write (?:a |an )?(?:function|program|method|class|query|script)|implement|code a|debug|refactor)\b", re.I)),
    ("proof", re.compile(r"\b(prove|show that|derive)\b", re.I)),
    ("numerical", re.compile(r"\b(calculate|compute|evaluate|find the value|solve for|how many|what is the)\b", re.I)),
    ("short_answer", re.compile(r"\b(define|name the|list the|state the|identify)\b", re.I)),
    ("descriptive", re.compile(r"\b(explain|describe|discuss|compare|contrast|analyse|analyze|justify|why)\b", re.I)),
]

# ----------------------------------------------------------------------
# Difficulty signals
# ----------------------------------------------------------------------
_HARD_SIGNALS = re.compile(
    r"\b(optimi[sz]e|optimal|o\(1\)|constant space|in[- ]place|without using|concurrent|thread[- ]safe|"
    r"distributed|amortis|amortiz|prove|derive|asymptotic|np[- ]hard|lock[- ]free|scalab|"
    r"minimi[sz]e|maximi[sz]e|edge cases?|trade[- ]?offs?|design a system)\b",
    re.I,
)
_EASY_SIGNALS = re.compile(
    r"\b(define|what is|name the|list the|state the|simple|basic|identify|recall|label)\b", re.I
)
_MEDIUM_SIGNALS = re.compile(
    r"\b(implement|write a|explain|describe|compare|apply|calculate|solve|analyse|analyze)\b", re.I
)

# Numeric bands for the three labels. Difficulty is carried as a 0..1 score because
# PS8's API contract returns a float, while the UI and validators use the label.
# "expert" is accepted as an explicit target (difficulty_shift) or an explicit model
# label. The estimator bands below deliberately still stop at "hard", so no existing
# seed is re-labelled by adding it.
DIFFICULTY_SCORES: dict[str, float] = {"easy": 0.25, "medium": 0.55, "hard": 0.85, "expert": 0.95}
_LABEL_BANDS: list[tuple[float, str]] = [(0.40, "easy"), (0.70, "medium"), (1.01, "hard")]


def score_to_label(score: float) -> str:
    for upper, label in _LABEL_BANDS:
        if score < upper:
            return label
    return "hard"


def label_to_score(label: str) -> float:
    return DIFFICULTY_SCORES.get((label or "").lower(), 0.55)


def estimate_difficulty(text: str) -> tuple[str, float]:
    """Heuristic difficulty from linguistic and structural signals.

    This is an explainable proxy, not a trained model - the README states that
    plainly. It combines explicit complexity signals with question length, which
    correlates with the number of requirements a learner must juggle.
    """
    t = text or ""
    score = 0.50

    if _HARD_SIGNALS.search(t):
        score += 0.25
    if _MEDIUM_SIGNALS.search(t):
        score += 0.05
    if _EASY_SIGNALS.search(t):
        score -= 0.20

    # Multi-part questions are harder than single-clause ones.
    n_tokens = len(content_tokens(t))
    if n_tokens > 45:
        score += 0.12
    elif n_tokens > 25:
        score += 0.06
    elif n_tokens < 8:
        score -= 0.08

    # Explicit complexity requirements are a strong "hard" signal.
    if re.search(r"o\(\s*(?:n\s*log\s*n|log\s*n|1|n)\s*\)", t, re.I):
        score += 0.08

    score = max(0.05, min(0.98, score))
    return score_to_label(score), round(score, 3)


def detect_question_type(text: str, domain_id: str) -> str:
    for qtype, pattern in _TYPE_PATTERNS:
        if pattern.search(text or ""):
            return qtype
    return domains.get_domain(domain_id).default_question_type


def extract_core_concept(text: str, domain_id: str) -> str:
    """Pick the most topical phrase from the seed.

    Prefers a domain keyword plus its neighbour (e.g. "linked list", "binary tree"),
    which is what makes concept-overlap checks meaningful later.
    """
    tokens = content_tokens(text)
    if not tokens:
        return (text or "").strip()[:60] or "unspecified concept"

    domain_kws = set(domains.get_domain(domain_id).keywords)
    for i, tok in enumerate(tokens):
        if tok in domain_kws:
            # Grab a short phrase around the keyword for a more specific concept.
            window = tokens[max(0, i - 1) : i + 2]
            return " ".join(window)
    return " ".join(tokens[:3])


def extract_topic(text: str, domain_id: str) -> str:
    concept = extract_core_concept(text, domain_id)
    return concept.title() if concept else domains.get_domain(domain_id).label


def build_learning_objective(text: str, qtype: str, concept: str) -> str:
    verb = {
        "coding": "implement",
        "numerical": "calculate",
        "proof": "prove",
        "mcq": "identify",
        "fill_in_the_blank": "recall",
        "true_false": "evaluate",
        "short_answer": "define",
        "descriptive": "explain",
    }.get(qtype, "apply")
    return f"The learner should be able to {verb} {concept}."


def heuristic_parse(seed: str, domain_hint: str | None = None) -> SeedMetadata:
    """Deterministic parse. Always succeeds; never touches the network."""
    seed = (seed or "").strip()
    domain_id = (
        domain_hint.lower()
        if domain_hint and domains.is_supported(domain_hint)
        else domains.infer_domain(seed)
    )
    qtype = detect_question_type(seed, domain_id)
    concept = extract_core_concept(seed, domain_id)
    label, score = estimate_difficulty(seed)

    return SeedMetadata(
        domain=domain_id,
        topic=extract_topic(seed, domain_id),
        subtopic=None,
        core_concept=concept,
        question_type=qtype,
        difficulty=label,  # type: ignore[arg-type]
        difficulty_score=score,
        learning_objective=build_learning_objective(seed, qtype, concept),
        keywords=sorted(set(content_tokens(seed)))[:12],
        raw_seed=seed,
    )


_SEED_PARSE_SYSTEM = (
    "You are an assessment-design analyst. You read one seed question and return "
    "only a JSON object describing it. Never invent a different question."
)

_SEED_PARSE_PROMPT = """Analyse this seed question and return ONLY a JSON object.

SEED QUESTION:
{seed}

Return exactly this JSON shape:
{{
  "topic": "short topic name",
  "subtopic": "more specific subtopic, or null",
  "core_concept": "the single concept being assessed, 2-5 words",
  "question_type": "one of: coding, mcq, fill_in_the_blank, true_false, numerical, proof, short_answer, descriptive",
  "difficulty": "one of: easy, medium, hard",
  "learning_objective": "one sentence starting with 'The learner should be able to'"
}}
"""

_ALLOWED_TYPES = {
    "coding", "mcq", "fill_in_the_blank", "true_false",
    "numerical", "proof", "short_answer", "descriptive",
}


def parse_seed(
    seed: str, domain_hint: str | None = None, *, use_llm: bool = True
) -> SeedMetadata:
    """Parse a seed, preferring the local model but never depending on it.

    Each LLM-provided field is accepted only if it passes a sanity check; otherwise
    the heuristic value is kept. That way a partially malformed model response
    degrades one field at a time instead of failing the whole parse.
    """
    base = heuristic_parse(seed, domain_hint)
    if not use_llm:
        return base

    try:
        raw = ollama.generate(
            _SEED_PARSE_PROMPT.format(seed=seed),
            system=_SEED_PARSE_SYSTEM,
            temperature=0.1,
            max_tokens=320,
        )
    except OllamaUnavailable as exc:
        logger.warning("Seed parse falling back to heuristic: %s", exc)
        return base

    from .candidate_builder import extract_json_object  # local import avoids a cycle

    parsed, _warnings = extract_json_object(raw)
    if not parsed:
        logger.warning("Seed parse produced unusable JSON; keeping heuristic result")
        return base

    data = base.model_dump()

    topic = _clean_str(parsed.get("topic"))
    if topic:
        data["topic"] = topic[:80]

    subtopic = _clean_str(parsed.get("subtopic"))
    if subtopic and subtopic.lower() not in {"null", "none", "n/a"}:
        data["subtopic"] = subtopic[:80]

    concept = _clean_str(parsed.get("core_concept"))
    if concept and 2 <= len(concept) <= 80:
        data["core_concept"] = concept

    qtype = _clean_str(parsed.get("question_type")).lower().replace("-", "_").replace(" ", "_")
    if qtype in _ALLOWED_TYPES:
        data["question_type"] = qtype

    difficulty = _clean_str(parsed.get("difficulty")).lower()
    if difficulty in DIFFICULTY_SCORES:
        data["difficulty"] = difficulty
        # Blend the model's label with the heuristic score so a one-word label does
        # not throw away the structural signal we measured.
        data["difficulty_score"] = round(
            0.5 * label_to_score(difficulty) + 0.5 * base.difficulty_score, 3
        )

    objective = _clean_str(parsed.get("learning_objective"))
    if objective and len(objective) > 10:
        data["learning_objective"] = objective[:240]

    return SeedMetadata(**data)


def _clean_str(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return normalize(value).strip() and value.strip() or ""
