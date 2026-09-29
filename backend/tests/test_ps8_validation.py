"""PS8: structural validation - concept, difficulty, duplicates, meaningful variation."""

from __future__ import annotations

import pytest

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


class TestAnswerKeySubstance:
    """A coding answer key must be code; a description of a solution is not one."""

    PROSE_KEY = (
        "The function should traverse the list and reverse the pointers of each node, "
        "then return the new head of the reversed list."
    )

    def test_prose_answer_for_coding_question_fails(self, seed, candidate_factory):
        result = validate_candidate(
            candidate_factory(GOOD_VARIATION, answer_key=self.PROSE_KEY), seed
        )
        assert not result.passed
        assert result.checks["answer_key"]["has_code"] is False
        assert any("describes a solution" in r for r in result.reasons)

    @pytest.mark.parametrize(
        "code",
        [
            "def reverse(head):\n    prev = None\n    return prev",
            "public static Node reverse(Node head) { return head; }",
            "function reverse(head) { return null; }",
            "Node* reverse(Node* head) {\n  return head;\n}",
        ],
    )
    def test_code_in_any_common_language_passes(self, seed, candidate_factory, code):
        result = validate_candidate(candidate_factory(GOOD_VARIATION, answer_key=code), seed)
        assert result.checks["answer_key"]["has_code"] is True
        assert not any("answer key" in r for r in result.reasons)

    def test_non_coding_question_does_not_need_code(self, seed, candidate_factory):
        result = validate_candidate(
            candidate_factory(
                GOOD_VARIATION,
                question_type="descriptive",
                answer_key="The reversed list is 4 -> 3 -> 2 -> 1, because each pointer flips.",
            ),
            seed.model_copy(update={"question_type": "descriptive"}),
        )
        assert result.checks["answer_key"]["has_code"] is None
        assert result.checks["answer_key"]["substantive"] is True

    def test_non_coding_stub_answer_fails(self, seed, candidate_factory):
        result = validate_candidate(
            candidate_factory(GOOD_VARIATION, question_type="descriptive", answer_key="Yes."),
            seed.model_copy(update={"question_type": "descriptive"}),
        )
        assert not result.checks["answer_key"]["substantive"]
        assert any("too short" in r for r in result.reasons)


class TestSolutionMethodAxis:
    """Coding variations rotate a solution method, and the method is verified."""

    # A real Qwen output from the first live run, rejected then as a "paraphrase"
    # (0.84 similarity to the seed) even though it changes the method to recursion.
    RECURSION_VARIATION = (
        "Design and implement a function to reverse a linked list using recursion. The "
        "function should take the head of the list as input and return the new head of "
        "the reversed list. Assume the linked list is singly linked and contains "
        "integer values."
    )

    def test_planner_rotates_methods_across_strategies(self, seed):
        from backend.app.ps8 import variation_planner

        plan = variation_planner.plan_variations(seed, 20)
        assert [p.method for p in plan[:4]] == ["iterative", "recursive", "auxiliary", "rebuild"]
        pairs = {(p.strategy, p.method) for p in plan}
        assert len(pairs) == 20  # every strategy x method pairing, no repeats

    def test_non_coding_seed_has_no_method_axis(self, seed):
        from backend.app.ps8 import variation_planner

        descriptive = seed.model_copy(update={"question_type": "descriptive"})
        assert all(p.method is None for p in variation_planner.plan_variations(descriptive, 5))

    def test_recursion_variation_is_now_accepted(self, seed, candidate_factory):
        from backend.tests.conftest import RECURSIVE_SOLUTION

        result = validate_candidate(
            candidate_factory(
                self.RECURSION_VARIATION,
                answer_key=RECURSIVE_SOLUTION,
                solution_method="recursive",
            ),
            seed,
        )
        assert 0.80 < result.semantic_similarity <= settings.method_variation_similarity_max
        assert result.checks["method"]["changed_from_default"] is True
        assert result.passed, result.reasons

    def test_same_text_without_a_verified_method_is_still_a_paraphrase(
        self, seed, candidate_factory
    ):
        # Iterative answer: the method did not actually change, so no allowance.
        result = validate_candidate(
            candidate_factory(self.RECURSION_VARIATION, solution_method="iterative"), seed
        )
        assert not result.passed
        assert any("paraphrase" in r for r in result.reasons)

    def test_planned_recursion_with_a_loop_answer_is_rejected(self, seed, candidate_factory):
        result = validate_candidate(
            candidate_factory(self.RECURSION_VARIATION, solution_method="recursive"), seed
        )
        assert not result.passed
        assert result.checks["method"]["used_in_answer"] is False
        assert any("solution method mismatch" in r for r in result.reasons)

    def test_method_must_be_asked_for_in_the_question(self, seed, candidate_factory):
        from backend.tests.conftest import RECURSIVE_SOLUTION

        result = validate_candidate(
            candidate_factory(
                GOOD_VARIATION, answer_key=RECURSIVE_SOLUTION, solution_method="recursive"
            ),
            seed,
        )
        assert result.checks["method"]["required_by_question"] is False
        assert any("solution method not required" in r for r in result.reasons)

    @pytest.mark.parametrize(
        "method_id, answer, expected",
        [
            ("recursive", "public Node rev(Node h) { if (h == null) return h; return rev(h.next); }", True),
            ("recursive", "def rev(head):\n    while head:\n        head = head.next\n    return head", False),
            ("auxiliary", "def rev(head):\n    stack = []\n    while head:\n        stack.append(head)", True),
            ("rebuild", "def rev(head):\n    out = None\n    while head:\n        out = ListNode(head.val, out)", True),
            ("rebuild", "def rev(head):\n    prev = None\n    while head:\n        head.next, prev, head = prev, head, head.next", False),
        ],
    )
    def test_method_evidence_detection(self, method_id, answer, expected):
        from backend.app.ps8 import methods

        assert methods.get_method(method_id).evidenced_in_answer(answer) is expected


class TestMethodEvidenceIgnoresScaffolding:
    """Regressions from the first live method run: in-place answers passed as rebuilds."""

    # Real Qwen answer accepted as a "rebuild": it rewires the input in place and only
    # mentions ListNode( in its asserts.
    IN_PLACE_WITH_TESTS = (
        "def reverse_books(head):\n"
        "    prev = None\n"
        "    current = head\n"
        "    while current:\n"
        "        next_node = current.next\n"
        "        current.next = prev\n"
        "        prev = current\n"
        "        current = next_node\n"
        "    return prev\n"
        "\n"
        "# Test cases\n"
        "assert reverse_books(ListNode('A', ListNode('B'))) == ListNode('B', ListNode('A'))\n"
    )

    def test_asserts_do_not_count_as_a_rebuild(self):
        from backend.app.ps8 import methods

        assert not methods.get_method("rebuild").evidenced_in_answer(self.IN_PLACE_WITH_TESTS)

    def test_asserts_do_not_count_as_recursion(self):
        from backend.app.ps8 import methods

        assert not methods.get_method("recursive").evidenced_in_answer(self.IN_PLACE_WITH_TESTS)

    def test_dummy_sentinel_node_is_not_a_rebuild(self):
        from backend.app.ps8 import methods

        code = "def rev(head):\n    dummy = ListNode(0)\n    dummy.next = head\n    return dummy.next"
        assert not methods.get_method("rebuild").evidenced_in_answer(code)

    def test_helper_calling_another_function_is_not_recursion(self):
        from backend.app.ps8 import methods

        code = (
            "def outer(head):\n    return inner(head)\n\n"
            "def inner(node):\n    prev = None\n    while node:\n        node = node.next\n    return prev"
        )
        assert not methods.get_method("recursive").evidenced_in_answer(code)


class TestDataStructureAnchor:
    """A programming variation must stay on the seed's data structure."""

    # Real Qwen output accepted in the second method run: an array, not a linked list.
    ARRAY_DRIFT = (
        "Write a function to reverse the elements in an array of integers using an "
        "auxiliary stack. The function should take an array as input and return the "
        "reversed array."
    )

    def test_seed_anchor_is_the_first_structure_named(self, seed):
        assert validators.seed_data_structure(seed) == "linked list"
        queue_seed = seed.model_copy(update={"raw_seed": "Reverse a queue using a stack."})
        assert validators.seed_data_structure(queue_seed) == "queue"

    def test_drift_to_an_array_is_rejected(self, seed, candidate_factory):
        result = validate_candidate(candidate_factory(self.ARRAY_DRIFT), seed)
        assert not result.concept_preserved
        assert any("different data structure" in r for r in result.reasons)

    @pytest.mark.parametrize(
        "question",
        [
            GOOD_VARIATION,
            "Pancakes are stored as a stack in a singly linked list; reverse the list.",
            "Reverse a doubly linked list of browser tabs in place and return the new head.",
        ],
    )
    def test_questions_on_the_same_structure_keep_the_concept(
        self, seed, candidate_factory, question
    ):
        result = validators.validate_concept(candidate_factory(question), seed)
        assert not any("different data structure" in r for r in result.reasons)

    def test_non_programming_seed_has_no_anchor(self, seed):
        maths = seed.model_copy(update={"domain": "mathematics"})
        assert validators.seed_data_structure(maths) is None


class TestRebuildMustNotRewire:
    def test_copy_plus_in_place_rewiring_is_not_a_rebuild(self):
        from backend.app.ps8 import methods

        code = (
            "def rev(head):\n    first = ListNode(head.val)\n    prev = None\n"
            "    while head:\n        nxt = head.next\n        head.next = prev\n"
            "        prev, head = head, nxt\n    return prev"
        )
        assert not methods.get_method("rebuild").evidenced_in_answer(code)

    def test_building_forward_with_a_tail_is_a_rebuild(self):
        from backend.app.ps8 import methods

        code = (
            "def copy_list(head):\n    dummy = ListNode(0)\n    tail = dummy\n"
            "    while head:\n        tail.next = ListNode(head.val)\n"
            "        tail = tail.next\n        head = head.next\n    return dummy.next"
        )
        assert methods.get_method("rebuild").evidenced_in_answer(code)
