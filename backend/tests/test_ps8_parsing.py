"""PS8: seed parsing, strategy selection and the tolerant JSON parser."""

from __future__ import annotations

import pytest

from backend.app.ps8 import domains, seed_parser, variation_planner
from backend.app.ps8.candidate_builder import build_candidate, extract_json_object


class TestSeedParser:
    def test_extracts_programming_metadata(self):
        seed = seed_parser.heuristic_parse("Write a function to reverse a singly linked list.")
        assert seed.domain == "programming"
        assert seed.question_type == "coding"
        assert "linked" in seed.core_concept
        assert seed.learning_objective.startswith("The learner should be able to")
        assert seed.raw_seed

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Find the derivative of f(x) = 3x^2 + 5x - 7.", "mathematics"),
            ("Explain why water has a higher boiling point than methane.", "science"),
            ("Describe how insulin regulates blood glucose levels.", "health"),
            ("Calculate the break-even point given fixed costs and margin.", "business"),
            ("Identify the subject and predicate in this sentence.", "language"),
        ],
    )
    def test_infers_domain_from_text(self, text, expected):
        assert domains.infer_domain(text) == expected

    def test_explicit_domain_hint_wins(self):
        seed = seed_parser.heuristic_parse("Explain the concept.", "business")
        assert seed.domain == "business"

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Write a function to sort an array.", "coding"),
            ("Which of the following is a stack operation?", "mcq"),
            ("The capital of France is ___.", "fill_in_the_blank"),
            ("Prove that the sum of two even numbers is even.", "proof"),
            ("Calculate the mean of the dataset.", "numerical"),
            ("Explain why hash collisions occur.", "descriptive"),
        ],
    )
    def test_detects_question_type(self, text, expected):
        assert seed_parser.detect_question_type(text, "programming") == expected

    def test_difficulty_ordering_is_sensible(self):
        _, easy = seed_parser.estimate_difficulty("Define a stack.")
        _, medium = seed_parser.estimate_difficulty(
            "Write a function to reverse a singly linked list."
        )
        _, hard = seed_parser.estimate_difficulty(
            "Optimise the algorithm to reverse a linked list in O(1) constant space "
            "without using recursion, handling all edge cases and proving correctness."
        )
        assert easy < medium < hard

    def test_difficulty_label_matches_score_band(self):
        for text in ["Define a queue.", "Write a function to merge two sorted lists."]:
            label, score = seed_parser.estimate_difficulty(text)
            assert label == seed_parser.score_to_label(score)

    def test_heuristic_parse_is_deterministic(self):
        a = seed_parser.heuristic_parse("Write a function to reverse a singly linked list.")
        b = seed_parser.heuristic_parse("Write a function to reverse a singly linked list.")
        assert a.model_dump() == b.model_dump()


class TestVariationPlanner:
    def test_rotates_through_all_strategies(self, seed):
        plan = variation_planner.plan_variations(seed, 5)
        assert len({p.strategy for p in plan}) == 5

    def test_generates_requested_count(self, seed):
        assert len(variation_planner.plan_variations(seed, 12)) == 12

    def test_repeat_cycles_ask_for_a_different_angle(self, seed):
        plan = variation_planner.plan_variations(seed, 7)
        # Item 5 reuses the strategy of item 0 but must carry extra guidance.
        assert plan[5].strategy == plan[0].strategy
        assert len(plan[5].instruction) > len(plan[0].instruction)

    def test_difficulty_shift_removes_difficulty_from_preserve(self, seed):
        plan = variation_planner.plan_variations(seed, 3, difficulty_shift="hard")
        assert all("difficulty" not in p.preserve for p in plan)
        assert all(any("hard" in c for c in p.change) for p in plan)

    def test_zero_count_returns_empty_plan(self, seed):
        assert variation_planner.plan_variations(seed, 0) == []


class TestMalformedJsonParsing:
    """The local 7B model emits all of these; none may crash the pipeline."""

    def test_clean_json(self):
        parsed, warnings = extract_json_object('{"question": "What is a stack?"}')
        assert parsed["question"] == "What is a stack?"
        assert warnings == []

    def test_markdown_fenced(self):
        parsed, warnings = extract_json_object('```json\n{"question": "Q?"}\n```')
        assert parsed["question"] == "Q?"
        assert any("fence" in w for w in warnings)

    def test_surrounded_by_prose(self):
        parsed, _ = extract_json_object('Sure! Here it is:\n{"question": "Q?"}\nHope that helps.')
        assert parsed["question"] == "Q?"

    def test_trailing_comma(self):
        parsed, warnings = extract_json_object('{"question": "Q?", "answer_key": "A",}')
        assert parsed["answer_key"] == "A"
        assert any("repair" in w for w in warnings)

    def test_unquoted_keys(self):
        parsed, _ = extract_json_object('{question: "Q?", answer_key: "A"}')
        assert parsed["question"] == "Q?"

    def test_python_literals(self):
        parsed, _ = extract_json_object('{"question": "Q?", "ok": True, "x": None}')
        assert parsed["ok"] is True and parsed["x"] is None

    def test_truncated_object_is_closed(self):
        parsed, _ = extract_json_object('{"question": "A long question that got cut off"')
        assert parsed is not None
        assert "cut off" in parsed["question"]

    def test_list_response_uses_first_object(self):
        parsed, warnings = extract_json_object('[{"question": "First?"}, {"question": "Second?"}]')
        assert parsed["question"] == "First?"
        assert any("list" in w for w in warnings)

    def test_empty_output_returns_none(self):
        parsed, warnings = extract_json_object("")
        assert parsed is None and warnings

    def test_prose_only_returns_none(self):
        parsed, warnings = extract_json_object("I'm sorry, I can't help with that.")
        assert parsed is None and warnings


class TestCandidateBuilder:
    def test_builds_from_clean_output(self, seed, plan):
        raw = (
            '{"question": "Given a playlist stored as a singly linked list, write a '
            'function that reverses the playback order.", "answer_key": "Walk the list '
            'rewiring each next pointer to the previous node.", "difficulty": "medium"}'
        )
        cand = build_candidate(raw, seed, plan[0])
        assert cand is not None
        assert cand.difficulty == "medium"
        assert cand.variation_strategy == plan[0].strategy
        assert cand.id.startswith("q_")

    def test_rejects_output_with_no_question(self, seed, plan):
        assert build_candidate('{"answer_key": "only an answer"}', seed, plan[0]) is None

    def test_rejects_too_short_question(self, seed, plan):
        assert build_candidate('{"question": "Why?"}', seed, plan[0]) is None

    def test_missing_answer_key_is_warned_not_dropped(self, seed, plan):
        cand = build_candidate(
            '{"question": "Reverse the linked list of sensor readings in place."}',
            seed,
            plan[0],
        )
        assert cand is not None
        assert cand.answer_key == ""
        assert any("answer_key" in w for w in cand.parse_warnings)

    def test_invalid_difficulty_is_re_estimated(self, seed, plan):
        cand = build_candidate(
            '{"question": "Reverse a linked list of orders.", "answer_key": "A",'
            ' "difficulty": "extremely difficult"}',
            seed,
            plan[0],
        )
        assert cand.difficulty in {"easy", "medium", "hard"}
        assert any("difficulty" in w for w in cand.parse_warnings)

    def test_unwraps_nested_object(self, seed, plan):
        cand = build_candidate(
            '{"variation": {"question": "Reverse the linked list of train carriages.",'
            ' "answer_key": "Rewire pointers."}}',
            seed,
            plan[0],
        )
        assert cand is not None
        assert "carriages" in cand.question

    def test_coerces_non_string_answer(self, seed, plan):
        cand = build_candidate(
            '{"question": "Reverse a linked list of packets.",'
            ' "answer_key": ["step one", "step two"]}',
            seed,
            plan[0],
        )
        assert "step one" in cand.answer_key and "step two" in cand.answer_key

    def test_parses_test_cases(self, seed, plan):
        cand = build_candidate(
            '{"question": "Reverse a linked list of integers.", "answer_key": "A",'
            ' "test_cases": [{"input": "[1,2,3]", "expected_output": "[3,2,1]"}]}',
            seed,
            plan[0],
        )
        assert len(cand.test_cases) == 1
        assert cand.test_cases[0].expected_output == "[3,2,1]"


class TestCodeFencesInsideJson:
    """An answer_key containing a ```python block is still a JSON response."""

    RAW = (
        '{"question": "Reverse a singly linked list of train carriages in place.", '
        '"answer_key": "```python\\ndef reverse(head):\\n    return head\\n```", '
        '"difficulty": "medium", "test_cases": []}'
    )

    def test_valid_json_with_fenced_code_parses(self):
        parsed, warnings = extract_json_object(self.RAW)
        assert parsed is not None and "def reverse" in parsed["answer_key"]
        assert warnings == []

    def test_json_with_fenced_code_inside_prose_still_parses(self):
        parsed, _ = extract_json_object("Here you go:\n" + self.RAW)
        assert parsed is not None and "def reverse" in parsed["answer_key"]

    def test_genuinely_fenced_json_still_unwrapped(self):
        parsed, warnings = extract_json_object("```json\n" + self.RAW + "\n```")
        assert parsed is not None


class TestAnswerKeyFences:
    def test_fences_are_stripped_from_the_answer_key(self, seed, plan):
        from backend.app.ps8.candidate_builder import build_candidate

        raw = (
            '{"question": "Reverse a singly linked list of playing cards in place.", '
            '"answer_key": "```python\\ndef reverse(head):\\n    return head\\n```"}'
        )
        cand = build_candidate(raw, seed, plan[0])
        assert "```" not in cand.answer_key
        assert cand.answer_key.startswith("def reverse(head):")
        assert any("fences" in w for w in cand.parse_warnings)
