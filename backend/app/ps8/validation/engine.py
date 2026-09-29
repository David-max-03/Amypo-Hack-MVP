"""Structural Validation Engine (PS8).

Runs the structural validators and merges them into the single StructuralValidation result
the API contract and the decision engine consume.
"""

from __future__ import annotations

from ...schemas import Candidate, SeedMetadata, StructuralValidation
from . import validators


def validate_candidate(
    candidate: Candidate,
    seed: SeedMetadata,
    *,
    previously_generated: list[str] | None = None,
    previously_accepted: list[str] | None = None,
    difficulty_shift: str | None = None,
) -> StructuralValidation:
    """Run every PS8 structural check on one candidate."""
    concept = validators.validate_concept(candidate, seed)
    difficulty = validators.validate_difficulty(
        candidate, seed, difficulty_shift=difficulty_shift
    )
    duplicate = validators.validate_duplicate(
        candidate,
        seed,
        previously_generated=previously_generated,
        previously_accepted=previously_accepted,
    )
    method = validators.validate_method(candidate)
    variation = validators.validate_variation(
        candidate, seed, method_changed=method.changed_from_default
    )
    answer_key = validators.validate_answer_key(candidate, seed)

    reasons: list[str] = [
        *concept.reasons,
        *difficulty.reasons,
        *duplicate.reasons,
        *variation.reasons,
        *answer_key.reasons,
        *method.reasons,
    ]

    # PS8 makes a correct answer key mandatory for every variation.
    passed = (
        concept.preserved
        and difficulty.matched
        and not duplicate.is_duplicate
        and variation.meaningful
        and answer_key.substantive
        and method.ok
    )

    return StructuralValidation(
        concept_preserved=concept.preserved,
        difficulty_match=difficulty.matched,
        is_duplicate=duplicate.is_duplicate,
        meaningful_variation=variation.meaningful,
        passed=passed,
        semantic_similarity=variation.similarity_to_seed,
        lexical_similarity=variation.lexical_to_seed,
        concept_overlap=concept.overlap,
        difficulty_delta=difficulty.delta,
        nearest_match=duplicate.nearest_match,
        nearest_match_source=duplicate.nearest_source,
        reasons=reasons,
        checks={
            "concept": {
                "preserved": concept.preserved,
                "keyword_overlap": concept.overlap,
                "semantic_similarity_to_objective": concept.semantic_similarity,
            },
            "difficulty": {
                "matched": difficulty.matched,
                "candidate": difficulty.candidate_label,
                "target": difficulty.target_label,
                "delta": difficulty.delta,
            },
            "duplicate": {
                "is_duplicate": duplicate.is_duplicate,
                "max_semantic_similarity": duplicate.semantic_similarity,
                "max_lexical_similarity": duplicate.lexical_similarity,
                "nearest_source": duplicate.nearest_source,
            },
            "variation": {
                "meaningful": variation.meaningful,
                "semantic_similarity_to_seed": variation.similarity_to_seed,
                "lexical_similarity_to_seed": variation.lexical_to_seed,
            },
            "answer_key_present": answer_key.present,
            "method": {
                "planned": method.method,
                "used_in_answer": method.in_answer,
                "required_by_question": method.in_question,
                "changed_from_default": method.changed_from_default,
            },
            "answer_key": {
                "present": answer_key.present,
                "substantive": answer_key.substantive,
                "has_code": answer_key.has_code,
            },
        },
    )


def compute_duplicate_rate(questions: list[str]) -> float:
    """Fraction of questions that are near-duplicates of an earlier one in the list.

    This is the metric PS8's automated scorer targets (<10%). Measured pairwise with
    the same thresholds the duplicate validator uses.
    """
    from ...config import settings
    from ...core.embeddings import embeddings
    from ...core.text_utils import jaccard

    if len(questions) < 2:
        return 0.0

    sim = embeddings.similarity_matrix(questions, questions)
    duplicates = 0
    for i in range(1, len(questions)):
        for j in range(i):
            semantic = float(sim[i][j])
            lexical = jaccard(questions[i], questions[j])
            if (
                semantic >= settings.duplicate_semantic_max
                or lexical >= settings.duplicate_lexical_max
            ):
                duplicates += 1
                break  # count each question at most once

    return round(duplicates / len(questions), 4)
