"""The four PS8 structural validators.

Each returns a small result object with a boolean plus the numbers behind it, so the
UI and the regeneration prompt can both explain *why* something failed rather than
just that it did. Every threshold comes from `settings` - none are hard-coded here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...config import settings
from ...core.embeddings import embeddings
from ...core.text_utils import jaccard, overlap_coefficient
from ...schemas import Candidate, SeedMetadata


@dataclass
class ConceptResult:
    preserved: bool
    overlap: float
    semantic_similarity: float
    reasons: list[str] = field(default_factory=list)


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
def validate_concept(candidate: Candidate, seed: SeedMetadata) -> ConceptResult:
    """Does the candidate still assess the seed's core concept?

    Combines lexical overlap against the concept phrase with semantic similarity
    against the learning objective. A candidate passes if either signal is strong -
    a scenario variation legitimately shares few words with the seed, so demanding
    both would reject exactly the variations PS8 wants.
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

    if not preserved:
        reasons.append(
            f"concept not preserved: only {overlap:.2f} keyword overlap with core concept "
            f"'{seed.core_concept}' and {semantic:.2f} semantic similarity to the seed's "
            f"learning objective (need >= {settings.concept_min_overlap:.2f} keyword "
            f"overlap or >= {settings.concept_min_semantic:.2f} semantic similarity)"
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
def validate_variation(candidate: Candidate, seed: SeedMetadata) -> VariationResult:
    """Is the candidate genuinely different from the seed, not just reworded?

    This is the mirror image of duplicate detection and is scored against the seed
    only. The acceptable band is bounded on both sides: too similar is a paraphrase,
    too dissimilar means the learning objective was lost.
    """
    semantic = embeddings.similarity(candidate.question, seed.raw_seed)
    lexical = jaccard(candidate.question, seed.raw_seed)

    reasons: list[str] = []
    meaningful = True

    if semantic > settings.variation_similarity_max:
        meaningful = False
        reasons.append(
            f"not a meaningful variation: {semantic:.2f} semantic similarity to the seed "
            f"reads as a paraphrase (max {settings.variation_similarity_max:.2f})"
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
