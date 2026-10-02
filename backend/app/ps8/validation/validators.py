"""The PS8 structural validators.

Each returns a small result object with a boolean plus the numbers behind it, so the
UI and the regeneration prompt can both explain *why* something failed rather than
just that it did. Every threshold comes from `settings` - none are hard-coded here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...config import settings
from ...core.embeddings import embeddings
from ...core.text_utils import jaccard, overlap_coefficient
from ...schemas import Candidate, SeedMetadata
from .. import contract as seed_contract
from .. import methods


@dataclass
class ConceptResult:
    preserved: bool
    overlap: float
    semantic_similarity: float
    reasons: list[str] = field(default_factory=list)
    # Required elements of the seed contract the question no longer mentions, and
    # how each of the others was matched (present / acronym / synonym).
    missing_elements: list[str] = field(default_factory=list)
    element_matches: dict[str, str] = field(default_factory=dict)


@dataclass
class DifficultyResult:
    matched: bool
    delta: float
    candidate_label: str
    target_label: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class DuplicateResult:
    is_duplicate: bool
    semantic_similarity: float
    lexical_similarity: float
    nearest_match: str | None = None
    nearest_source: str | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class VariationResult:
    meaningful: bool
    similarity_to_seed: float
    lexical_to_seed: float
    reasons: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------
# A. Concept preservation
# ----------------------------------------------------------------------
# Core data structures a programming seed can be "about". Order matters only for
# readability; the seed's anchor is whichever appears earliest in the seed text.
_DATA_STRUCTURES: dict[str, str] = {
    "linked list": r"linked[\s-]?lists?",
    "binary tree": r"\b(binary\s+)?(search\s+)?trees?\b|\bbst\b",
    "graph": r"\bgraphs?\b",
    "matrix": r"\bmatri(x|ces)\b|\b2d\s+arrays?\b|\bgrids?\b",
    "heap": r"\bheaps?\b|priority\s+queues?",
    "hash map": r"hash\s*(map|table)s?|\bdictionar(y|ies)\b",
    "array": r"\barrays?\b",
    "string": r"\bstrings?\b",
    "stack": r"\bstacks?\b",
    "queue": r"\bqueues?\b",
}


def seed_data_structure(seed: SeedMetadata) -> str | None:
    """The data structure a programming seed is about: the earliest one it names."""
    if seed.domain != "programming":
        return None
    found: list[tuple[int, str]] = []
    for name, pattern in _DATA_STRUCTURES.items():
        m = re.search(pattern, seed.raw_seed, re.I)
        if m:
            found.append((m.start(), name))
    return min(found)[1] if found else None


def validate_concept(candidate: Candidate, seed: SeedMetadata) -> ConceptResult:
    """Does the candidate still assess the seed's core concept?

    Three independent signals, because no single similarity score separates
    "lexically close but about something else" from "lexically far but faithful":

      1. overlap with the concept phrase OR similarity to the learning objective -
         a scenario variation legitimately shares few words with the seed, so either
         signal may carry it;
      2. the seed contract's required elements - the terms measured to carry the
         seed's concept, and any technology it names - must all still be present
         (literally, by acronym, or by a new word that means the same);
      3. a programming seed's data structure is a hard anchor.

    Signals 2 and 3 can only fail a candidate, never rescue one.
    """
    concept_text = f"{seed.core_concept} {seed.topic}"
    overlap = overlap_coefficient(candidate.question, concept_text)
    semantic = embeddings.similarity(
        f"{candidate.question} {candidate.learning_objective}",
        f"{seed.raw_seed} {seed.learning_objective}",
    )

    reasons: list[str] = []
    lexical_ok = overlap >= settings.concept_min_overlap
    # Concept drift shows up as low similarity to the seed's objective. This floor is
    # separate from (and much higher than) the variation-drift floor: MiniLM gives
    # completely unrelated text roughly 0.2, so reusing that bound would pass anything.
    semantic_ok = semantic >= settings.concept_min_semantic
    preserved = lexical_ok or semantic_ok

    # Overlap and similarity both tolerate swapping the data structure ("reverse an
    # array with a stack" shares "reverse" and "stack" with a linked-list seed), so a
    # programming seed's data structure is a hard anchor.
    contract = seed_contract.get_contract(seed)
    anchor = contract.structure_anchor
    if anchor and not re.search(_DATA_STRUCTURES[anchor], candidate.question, re.I):
        preserved = False
        reasons.append(
            f"concept not preserved: the seed is about a {anchor}, but the question "
            f"never mentions one - it has drifted to a different data structure"
        )
    elif not preserved:
        reasons.append(
            f"concept not preserved: only {overlap:.2f} keyword overlap with core concept "
            f"'{seed.core_concept}' and {semantic:.2f} semantic similarity to the seed's "
            f"learning objective (need >= {settings.concept_min_overlap:.2f} keyword "
            f"overlap or >= {settings.concept_min_semantic:.2f} semantic similarity)"
        )

    missing, matches = seed_contract.missing_elements(
        contract, candidate.question, candidate.answer_key
    )
    if missing:
        preserved = False
        about = ", ".join(contract.required_elements + contract.named_elements)
        reasons.append(
            f"learning objective changed: the seed is about {about}, but the question no "
            f"longer mentions {', '.join(missing)} - it assesses something else"
        )

    if candidate.domain != seed.domain:
        reasons.append(
            f"domain drifted from '{seed.domain}' to '{candidate.domain}'"
        )

    return ConceptResult(
        preserved=preserved,
        overlap=round(overlap, 4),
        semantic_similarity=round(semantic, 4),
        reasons=reasons,
        missing_elements=missing,
        element_matches=matches,
    )


# ----------------------------------------------------------------------
# A2. Strategy compliance
# ----------------------------------------------------------------------
@dataclass
class StrategyResult:
    strategy: str
    # True / False when the change the strategy asks for can be checked from the
    # text; None when it cannot (recorded, never counted as a failure).
    followed: bool | None
    evidence: str
    reasons: list[str] = field(default_factory=list)


_CONSTRAINT_CUE_RE = re.compile(
    r"\b(only|must|cannot|can't|without|not allowed|not permitted|forbidden|prohibited|"
    r"do not use|don't use|may not|should not|no (?:built-in|additional|extra|external|more)|"
    r"at most|at least|limit(?:ed)?|restrict(?:ed|ion)?|maximum|exactly|single pass|"
    r"in-place|in place)\b|O\(",
    re.I,
)
_STRUCTURE_CUE_RE = re.compile(
    r"\b(bug|debug|fix|flaw(?:ed)?|faulty|incorrect|error|mistake|correct the|complete the|"
    r"partial|missing|fill in|trace|step[- ]by[- ]step|justify|predict|"
    r"what (?:is|does|will)[^.?]*(?:output|print|return|result)|"
    r"(?:the )?following (?:code|function|implementation|solution|query|proof|steps|program))\b",
    re.I,
)
_REPRESENTATION_CUE_RE = re.compile(
    r"\b(which of the following|choose|select the|options?|table|tabular|diagram|json|csv|"
    r"xml|matrix|format|formatted|represented as|representation|list of|array of|"
    r"dictionary|string of|true or false|fill in the blank|pseudocode)\b|^\s*[A-D][).]",
    re.I | re.M,
)


def validate_strategy(candidate: Candidate, seed: SeedMetadata) -> StrategyResult:
    """Did the candidate change the dimension its strategy varies?

    A candidate fails only where the text gives reliable evidence that the change
    did not happen: a scenario variation with no new setting, or a parameter
    variation that reuses the seed's values. A constraint, structure or
    representation change has many valid forms, so the absence of a recognised cue
    is reported as "not verifiable" (None), never as a failure.
    """
    contract = seed_contract.get_contract(seed)
    strategy = candidate.variation_strategy
    question = candidate.question

    if strategy == "scenario":
        seed_stems = {seed_contract.stem(t) for t in seed_contract.candidate_terms(seed.raw_seed)}
        terms = seed_contract.candidate_terms(question)
        fresh = [t for t in terms if seed_contract.stem(t) not in seed_stems]
        ratio = len(fresh) / len(terms) if terms else 0.0
        followed = len(fresh) >= 5 and ratio >= 0.4
        evidence = f"{len(fresh)} new content words ({ratio:.0%} of the question)"
        reason = (
            "strategy not followed: a scenario variation must place the task in a new "
            f"real-world setting, but the question adds only {evidence}"
        )
    elif strategy == "parameter":
        before, after = set(contract.parameters), set(seed_contract.parameters(question))
        if before:
            followed = bool(after - before)
            evidence = f"seed values {sorted(before)} -> question values {sorted(after)}"
        else:
            followed = True if after else None
            evidence = f"question states values {sorted(after)}" if after else "no concrete values to compare"
        reason = (
            "strategy not followed: a parameter variation must change the concrete "
            f"values, but the question reuses the seed's ({evidence})"
        )
    elif strategy == "constraint":
        new_clauses = [
            c for c in seed_contract.constraint_clauses(question) if c not in contract.constraints
        ]
        cue = _CONSTRAINT_CUE_RE.search(question) and not _CONSTRAINT_CUE_RE.search(seed.raw_seed)
        # A constraint can be worded in too many ways ("using recursion rather than a
        # loop") to treat an unrecognised one as absent, so this never fails a candidate.
        followed = True if (new_clauses or cue) else None
        evidence = (
            f"new constraint: {new_clauses[0]}" if new_clauses
            else "constraint wording present" if cue else "no recognised constraint wording"
        )
        reason = ""
    elif strategy == "structure":
        m = _STRUCTURE_CUE_RE.search(question)
        followed = True if m else None
        evidence = f"changed task shape: '{m.group(0)}'" if m else "no recognised cue"
        reason = ""
    elif strategy == "representation":
        m = _REPRESENTATION_CUE_RE.search(question)
        followed = True if m else None
        evidence = f"changed presentation: '{m.group(0).strip()}'" if m else "no recognised cue"
        reason = ""
    else:
        return StrategyResult(strategy=strategy or "", followed=None, evidence="unknown strategy")

    return StrategyResult(
        strategy=strategy,
        followed=followed,
        evidence=evidence,
        reasons=[reason] if followed is False else [],
    )


# ----------------------------------------------------------------------
# B. Difficulty equivalence
# ----------------------------------------------------------------------
def validate_difficulty(
    candidate: Candidate, seed: SeedMetadata, *, difficulty_shift: str | None = None
) -> DifficultyResult:
    """Is the candidate's difficulty equivalent to the seed (or the requested shift)?"""
    from ..seed_parser import label_to_score

    target_label = difficulty_shift or seed.difficulty
    target_score = (
        label_to_score(difficulty_shift) if difficulty_shift else seed.difficulty_score
    )

    delta = candidate.difficulty_score - target_score
    matched = abs(delta) <= settings.difficulty_tolerance

    reasons: list[str] = []
    if not matched:
        direction = "harder" if delta > 0 else "easier"
        reasons.append(
            f"difficulty mismatch: candidate is '{candidate.difficulty}' "
            f"({candidate.difficulty_score:.2f}) but target is '{target_label}' "
            f"({target_score:.2f}) - {abs(delta):.2f} {direction} than the allowed "
            f"tolerance of {settings.difficulty_tolerance:.2f}"
        )

    return DifficultyResult(
        matched=matched,
        delta=round(delta, 4),
        candidate_label=candidate.difficulty,
        target_label=target_label,
        reasons=reasons,
    )


# ----------------------------------------------------------------------
# C. Duplicate / near-duplicate detection
# ----------------------------------------------------------------------
def validate_duplicate(
    candidate: Candidate,
    seed: SeedMetadata,
    *,
    previously_generated: list[str] | None = None,
    previously_accepted: list[str] | None = None,
) -> DuplicateResult:
    """Compare the candidate against the seed, this run's output, and the stored bank.

    Uses both lexical (Jaccard) and semantic (MiniLM cosine) similarity: lexical
    catches near-verbatim copies, semantic catches reworded ones.
    """
    # (text, source label) pairs so the reason can say where the clash came from.
    corpus: list[tuple[str, str]] = [(seed.raw_seed, "seed question")]
    corpus += [(q, "earlier variation in this run") for q in (previously_generated or []) if q]
    corpus += [(q, "previously accepted question") for q in (previously_accepted or []) if q]

    if not corpus:
        return DuplicateResult(is_duplicate=False, semantic_similarity=0.0, lexical_similarity=0.0)

    texts = [t for t, _ in corpus]
    sem_scores = embeddings.similarity_matrix([candidate.question], texts)[0]
    lex_scores = [jaccard(candidate.question, t) for t in texts]

    # Judge each entry on its strongest signal, then take the worst offender.
    best_idx = max(range(len(texts)), key=lambda i: max(float(sem_scores[i]), lex_scores[i]))
    best_sem = float(sem_scores[best_idx])
    best_lex = lex_scores[best_idx]
    nearest_text, nearest_source = corpus[best_idx]

    reasons: list[str] = []
    is_duplicate = False

    if best_sem >= settings.duplicate_semantic_max:
        is_duplicate = True
        reasons.append(
            f"semantic similarity too high: {best_sem:.2f} against the {nearest_source} "
            f"(threshold {settings.duplicate_semantic_max:.2f})"
        )
    if best_lex >= settings.duplicate_lexical_max:
        is_duplicate = True
        reasons.append(
            f"lexical similarity too high: {best_lex:.2f} against the {nearest_source} "
            f"(threshold {settings.duplicate_lexical_max:.2f})"
        )

    return DuplicateResult(
        is_duplicate=is_duplicate,
        semantic_similarity=round(best_sem, 4),
        lexical_similarity=round(best_lex, 4),
        nearest_match=nearest_text[:300],
        nearest_source=nearest_source,
        reasons=reasons,
    )


# ----------------------------------------------------------------------
# D. Meaningful variation (reject plain paraphrases)
# ----------------------------------------------------------------------
def validate_variation(
    candidate: Candidate, seed: SeedMetadata, *, method_changed: bool = False
) -> VariationResult:
    """Is the candidate genuinely different from the seed, not just reworded?

    This is the mirror image of duplicate detection and is scored against the seed
    only. The acceptable band is bounded on both sides: too similar is a paraphrase,
    too dissimilar means the learning objective was lost. A verified change of
    solution method (`method_changed`) is a real variation even in similar words,
    so it gets the higher `method_variation_similarity_max` ceiling.
    """
    semantic = embeddings.similarity(candidate.question, seed.raw_seed)
    lexical = jaccard(candidate.question, seed.raw_seed)

    reasons: list[str] = []
    meaningful = True
    ceiling = (
        settings.method_variation_similarity_max
        if method_changed
        else settings.variation_similarity_max
    )

    if semantic > ceiling:
        meaningful = False
        reasons.append(
            f"not a meaningful variation: {semantic:.2f} semantic similarity to the seed "
            f"reads as a paraphrase (max {ceiling:.2f})"
        )
    if semantic < settings.variation_similarity_min:
        meaningful = False
        reasons.append(
            f"variation drifted too far: only {semantic:.2f} semantic similarity to the "
            f"seed (min {settings.variation_similarity_min:.2f}) - the learning objective "
            "may have been lost"
        )

    return VariationResult(
        meaningful=meaningful,
        similarity_to_seed=round(semantic, 4),
        lexical_to_seed=round(lexical, 4),
        reasons=reasons,
    )


# A reference solution must actually define something. "Return prev as the new head"
# mentions `return` but is prose; `def reverse(head):` is code.
_CODE_DEFINITION_RE = re.compile(
    r"\bdef\s+\w+\s*\("  # Python
    r"|\bfunction\s*\w*\s*\("  # JavaScript
    r"|\bclass\s+\w+"  # any OO language
    r"|\b(?:public|private|protected|static)\b[^\n]*\("  # Java / C#
    r"|\b(?:fn|func)\s+\w+\s*\("  # Rust / Go
    r"|^\s*[A-Za-z_][\w<>\[\]*&:]*\s+\**\w+\s*\([^)]*\)\s*\{",  # C / C++
    re.M,
)
# Code that is not a function: a query, markup, a style rule. "Write a SQL query"
# is answered by a SELECT statement, which defines nothing.
_CODE_ARTIFACT_RE = re.compile(
    r"\bSELECT\b[\s\S]{1,600}?\bFROM\b|\bINSERT\s+INTO\b|\bUPDATE\s+\w+\s+SET\b"
    r"|\bDELETE\s+FROM\b|\bCREATE\s+(?:TABLE|INDEX|VIEW)\b"  # SQL
    r"|<\s*[a-zA-Z][\w-]*(?:\s+[^<>]*)?>[\s\S]*<\s*/\s*[a-zA-Z][\w-]*\s*>"  # markup
    r"|[.#]?[\w-]+\s*\{[^{}]*:[^{}]*\}",  # a style rule
    re.I,
)


@dataclass
class AnswerKeyResult:
    present: bool
    substantive: bool
    has_code: bool | None  # None when the question is not a coding question
    reasons: list[str] = field(default_factory=list)


def _is_coding_question(candidate: Candidate, seed: SeedMetadata) -> bool:
    qtype = f"{candidate.question_type} {seed.question_type}".lower()
    return "coding" in qtype or "program" in qtype


def validate_answer_key(candidate: Candidate, seed: SeedMetadata) -> AnswerKeyResult:
    """Is the answer key an actual answer, not a description of one?

    PS8 scores answer-key correctness. A key that says "the function should reverse
    the list in O(n)" cannot be used to mark a submission, so for coding questions we
    require a reference implementation, and for every question a non-trivial answer.
    """
    text = candidate.answer_key.strip()
    if not text:
        return AnswerKeyResult(
            present=False,
            substantive=False,
            has_code=None,
            reasons=["missing answer key: PS8 requires an answer key for every variation"],
        )

    # The prompt's own placeholder, echoed back, is not an answer.
    from ..prompt_builder import ANSWER_HINTS  # local import avoids a cycle

    if any(jaccard(text, hint) >= 0.8 for hint in ANSWER_HINTS.values()):
        return AnswerKeyResult(
            present=True,
            substantive=False,
            has_code=None,
            reasons=[
                "answer key is too short to be usable: it repeats the prompt's placeholder "
                "text instead of giving an answer"
            ],
        )

    reasons: list[str] = []
    has_code: bool | None = None
    if _is_coding_question(candidate, seed):
        has_code = bool(_CODE_DEFINITION_RE.search(text) or _CODE_ARTIFACT_RE.search(text))
        if not has_code:
            reasons.append(
                "answer key describes a solution instead of giving one: a coding "
                "question needs a complete reference implementation in code"
            )
    elif len(text.split()) < settings.answer_key_min_words:
        reasons.append(
            f"answer key is too short to be usable ({len(text.split())} words; "
            f"minimum {settings.answer_key_min_words})"
        )

    return AnswerKeyResult(
        present=True,
        substantive=not reasons,
        has_code=has_code,
        reasons=reasons,
    )


@dataclass
class MethodResult:
    method: str | None
    in_answer: bool | None  # None when the variation has no planned method
    in_question: bool | None
    changed_from_default: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.reasons


def validate_method(candidate: Candidate) -> MethodResult:
    """Does the variation actually use the solution method it was planned with?

    Without this check a method label is just the model's say-so. The answer key
    must implement the method; for non-default methods the question must also ask
    for it, or a learner could solve it the usual way and the variation is moot.
    """
    method = methods.get_method(candidate.solution_method)
    if method is None:
        return MethodResult(None, None, None, False)

    in_answer = method.evidenced_in_answer(candidate.answer_key)
    in_question = method.evidenced_in_question(candidate.question)
    reasons: list[str] = []
    if not in_answer:
        reasons.append(
            f"solution method mismatch: planned {method.label.lower()}, but the answer "
            "key does not use it"
        )
    if not in_question:
        reasons.append(
            f"solution method not required: the question never asks for a "
            f"{method.label.lower()}, so learners could solve it the usual way"
        )
    return MethodResult(
        method=method.id,
        in_answer=in_answer,
        in_question=in_question,
        changed_from_default=(not method.is_default) and in_answer and in_question,
        reasons=reasons,
    )
