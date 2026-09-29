"""PS8: structural validation - concept, difficulty, duplicates, meaningful variation."""

from __future__ import annotations

from backend.app.config import settings
from backend.app.ps8.validation import validators
from backend.app.ps8.validation.engine import compute_duplicate_rate, validate_candidate

SEED_TEXT = "Write a function to reverse a singly linked list."

# A genuine scenario variation: same concept, entirely different surface.
GOOD_VARIATION = (
    "A music app stores its play queue as a singly linked list of track nodes. "
    "Implement a routine that reverses the queue so the last track plays first, "
    "rewiring the existing nodes rather than allocating a new queue."
)


class TestConceptValidator:
    def test_preserves_concept_for_genuine_variation(self, seed, candidate_factory):
        result = validators.validate_concept(candidate_factory(GOOD_VARIATION), seed)
        assert result.preserved
        assert result.reasons == []

    def test_flags_domain_drift(self, seed, candidate_factory):
        candidate = candidate_factory(GOOD_VARIATION, domain="mathematics")
        result = validators.validate_concept(candidate, seed)
        assert any("domain drifted" in r for r in result.reasons)

    def test_detects_total_concept_drift(self, seed, candidate_factory):
        off_topic = candidate_factory(
            "Describe the principal causes of the French Revolution and their "
            "relative importance to the events of 1789."
        )
        result = validators.validate_concept(off_topic, seed)
        assert not result.preserved
        assert any("concept not preserved" in r for r in result.reasons)


class TestDifficultyValidator:
    def test_equivalent_difficulty_passes(self, seed, candidate_factory):
        candidate = candidate_factory(GOOD_VARIATION, difficulty_score=seed.difficulty_score)
        assert validators.validate_difficulty(candidate, seed).matched

    def test_large_mismatch_fails_with_reason(self, seed, candidate_factory):
        candidate = candidate_factory(GOOD_VARIATION, difficulty="hard", difficulty_score=0.95)
        result = validators.validate_difficulty(candidate, seed)
        assert not result.matched
        assert any("difficulty mismatch" in r for r in result.reasons)
        assert result.delta > 0

    def test_requested_shift_changes_the_target(self, seed, candidate_factory):
        candidate = candidate_factory(GOOD_VARIATION, difficulty="hard", difficulty_score=0.85)
        # Against the seed's medium this fails; against an explicit hard target it passes.
        assert not validators.validate_difficulty(candidate, seed).matched
        assert validators.validate_difficulty(
            candidate, seed, difficulty_shift="hard"
        ).matched

    def test_tolerance_is_configurable(self, seed, candidate_factory, monkeypatch):
        candidate = candidate_factory(GOOD_VARIATION, difficulty_score=0.95)
        assert not validators.validate_difficulty(candidate, seed).matched
        monkeypatch.setattr(settings, "difficulty_tolerance", 0.9)
        assert validators.validate_difficulty(candidate, seed).matched


class TestDuplicateValidator:
    def test_distinct_variation_is_not_duplicate(self, seed, candidate_factory):
        result = validators.validate_duplicate(candidate_factory(GOOD_VARIATION), seed)
        assert not result.is_duplicate

    def test_verbatim_seed_copy_is_duplicate(self, seed, candidate_factory):
        result = validators.validate_duplicate(candidate_factory(SEED_TEXT), seed)
        assert result.is_duplicate
        assert result.nearest_source == "seed question"
        assert result.reasons

    def test_detects_duplicate_of_earlier_variation(self, seed, candidate_factory):
        result = validators.validate_duplicate(
            candidate_factory(GOOD_VARIATION),
            seed,
            previously_generated=[GOOD_VARIATION],
        )
        assert result.is_duplicate
        assert result.nearest_source == "earlier variation in this run"

    def test_detects_duplicate_of_accepted_question(self, seed, candidate_factory):
        result = validators.validate_duplicate(
            candidate_factory(GOOD_VARIATION),
            seed,
            previously_accepted=[GOOD_VARIATION],
        )
        assert result.is_duplicate
        assert result.nearest_source == "previously accepted question"

    def test_threshold_is_configurable(self, seed, candidate_factory, monkeypatch):
        candidate = candidate_factory(GOOD_VARIATION)
        assert not validators.validate_duplicate(candidate, seed).is_duplicate
        # Drop the bar far enough that anything on-topic counts as a duplicate.
        monkeypatch.setattr(settings, "duplicate_semantic_max", 0.05)
        assert validators.validate_duplicate(candidate, seed).is_duplicate


class TestVariationValidator:
    def test_genuine_variation_is_meaningful(self, seed, candidate_factory):
        assert validators.validate_variation(candidate_factory(GOOD_VARIATION), seed).meaningful

    def test_paraphrase_is_rejected(self, seed, candidate_factory):
        paraphrase = candidate_factory("Write a function that reverses a singly linked list.")
        result = validators.validate_variation(paraphrase, seed)
        assert not result.meaningful
        assert any("paraphrase" in r for r in result.reasons)

    def test_unrelated_question_drifted_too_far(self, seed, candidate_factory):
        unrelated = candidate_factory(
            "Name the principal exports of Portugal during the sixteenth century."
        )
        result = validators.validate_variation(unrelated, seed)
        assert not result.meaningful
        assert any("drifted too far" in r for r in result.reasons)


class TestValidationEngine:
    def test_good_candidate_passes_everything(self, seed, candidate_factory):
        result = validate_candidate(candidate_factory(GOOD_VARIATION), seed)
        assert result.passed
        assert result.concept_preserved and result.meaningful_variation
        assert not result.is_duplicate and result.difficulty_match
        assert result.reasons == []

    def test_missing_answer_key_fails(self, seed, candidate_factory):
        result = validate_candidate(candidate_factory(GOOD_VARIATION, answer_key=""), seed)
        assert not result.passed
        assert any("answer key" in r for r in result.reasons)

    def test_duplicate_fails_and_explains(self, seed, candidate_factory):
        result = validate_candidate(candidate_factory(SEED_TEXT), seed)
        assert not result.passed
        assert result.is_duplicate
        assert any("similarity too high" in r for r in result.reasons)

    def test_checks_dict_is_fully_populated(self, seed, candidate_factory):
        result = validate_candidate(candidate_factory(GOOD_VARIATION), seed)
        for key in ("concept", "difficulty", "duplicate", "variation", "answer_key_present"):
            assert key in result.checks


class TestDuplicateRate:
    def test_empty_and_single(self):
        assert compute_duplicate_rate([]) == 0.0
        assert compute_duplicate_rate(["only one question here"]) == 0.0

    def test_all_distinct_is_zero(self):
        rate = compute_duplicate_rate([
            "Reverse a singly linked list of playlist tracks in place.",
            "Compute the total rainfall recorded across twelve weather stations.",
            "Explain how a hash table resolves collisions using chaining.",
        ])
        assert rate == 0.0

    def test_identical_entries_are_counted(self):
        q = "Reverse a singly linked list of playlist tracks in place."
        assert compute_duplicate_rate([q, q, q]) > 0.5
