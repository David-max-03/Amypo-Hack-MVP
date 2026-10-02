"""PS2 on generated questions: what is a factual claim and what is not.

A generated exam question is mostly instruction, premise and example. Holding those
to source grounding marked almost every candidate "unverifiable". These tests pin
the distinction - and pin that nothing which can actually be wrong is exempted.
"""

from __future__ import annotations

import pytest

from backend.app.decision.decision_engine import decide
from backend.app.ps2 import engine
from backend.app.ps2.response_analyzer import (
    classify_answer_sentence,
    classify_claim,
    classify_question_sentence,
    extract_claims,
    instance_tokens,
    mask_code,
)
from backend.app.schemas import StructuralValidation
from backend.tests.conftest import REFERENCE_SOLUTION, make_candidate

CHECKABLE = {"factual", "answer", "citation"}
PS8_OK = StructuralValidation(
    concept_preserved=True, difficulty_match=True, is_duplicate=False, meaningful_variation=True,
    passed=True, semantic_similarity=0.5, lexical_similarity=0.2, concept_overlap=0.5,
    difficulty_delta=0.0,
)
CODE_ONLY = "def reverse(head):\n    prev = None\n    while head:\n        head.next, prev, head = prev, head, head.next\n    return prev"


@pytest.fixture(scope="module", autouse=True)
def _warm():
    from backend.app.core.embeddings import embeddings

    embeddings.warm_up()


class TestQuestionSentences:
    @pytest.mark.parametrize("sentence", [
        "Check if the number 37 is prime.",
        "Write a SQL query to find duplicate email addresses in the members table.",
        "Then, explain the difference between unit testing and integration testing in this context.",
        "Use the provided test cases to validate your solution.",
        "Implement the function without using loops, and ensure that it does not exceed 10 recursive calls.",
        "How will the librarian decide which patron uses which computer next?",
        "The function should return -1 if the target is not found.",
        "The function should run in O(log n) time.",          # a requirement, not a claim
        "It must not use any additional data structures.",
        "Your solution must handle an empty list.",
        "You cannot use the GROUP BY clause.",
        "Do not use any built-in sorting function.",
    ])
    def test_instructions_and_requirements_are_not_claims(self, sentence):
        assert classify_question_sentence(sentence) == "instruction"

    @pytest.mark.parametrize("sentence", [
        "A local library maintains a database of its members.",
        "Each member has an email address.",
        "However, the function contains an error.",
        "The database is hosted on a read-only server.",
        "For example, is_prime(2) returns True and is_prime(4) returns False.",
        "Input: [1, 3, 5, 7, 9], target = 5",
        "P1 (arrival time: 0, burst time: 4)",
        "| 1  | Alice | alice@example.com |",
    ])
    def test_premises_and_examples_are_the_problems_own_givens(self, sentence):
        assert classify_question_sentence(sentence) == "setup"

    @pytest.mark.parametrize("sentence", [
        "You are developing a version control system for a small team.",
        "Assume the list is not empty.",
    ])
    def test_scenario_frames_stay_assumptions(self, sentence):
        assert classify_question_sentence(sentence) == "assumption"

    @pytest.mark.parametrize("sentence", [
        "A prime number is a natural number greater than 1 that has no positive divisors other than 1 and itself.",
        "Binary search is an algorithm that halves the search range at every step.",
        "A recursive reversal of a singly linked list uses O(1) space.",
        "Merge sort has a worst-case time complexity of O(n log n).",
        "Recursion is always slower than iteration.",
        "Quicksort is typically faster than merge sort in practice.",
        "A recursive solution must use O(n) stack space.",   # generic subject: a claim, not a requirement
    ])
    def test_general_statements_in_a_question_are_still_checked(self, sentence):
        assert classify_question_sentence(sentence) == "factual"

    def test_a_citation_in_a_question_is_still_a_citation(self):
        assert classify_question_sentence("According to the 2019 Stanford Algorithms Report, it is faster.") == "citation"


class TestAnswerSentences:
    @pytest.mark.parametrize("sentence", [
        "This query groups the members by their email addresses and counts each group.",
        "The HAVING clause filters out the emails that appear only once.",
        "The function iterates from 2 up to the square root of n.",
        "Here the loop stops as soon as a divisor is found.",
        "In this solution the minimum is tracked on a second stack.",
    ])
    def test_descriptions_of_the_candidates_own_solution(self, sentence):
        assert classify_answer_sentence(sentence, code_answer=True) == "explanation"
        assert classify_answer_sentence(sentence, code_answer=False) == "explanation"

    def test_pronoun_led_sentences_are_about_the_code_only_after_code(self):
        sentence = "It uses the class that most of those neighbours share."
        assert classify_answer_sentence(sentence, code_answer=True) == "explanation"
        # In a prose answer the same sentence is content, and stays checkable.
        assert classify_answer_sentence(sentence, code_answer=False) == "factual"

    def test_working_on_the_problems_own_values_is_not_a_general_fact(self):
        tokens = instance_tokens("Processes P1, P2 and P3 have burst times 4, 6 and 10 with a quantum of 2.")
        assert {"p1", "p3", "10", "2"} <= tokens
        assert classify_answer_sentence("Finally, P3 runs from time 6 to time 10.", code_answer=False, problem_tokens=tokens) == "explanation"
        # No value of this problem in it: a general statement about the method.
        general = "In round-robin scheduling, each process is given a fixed time slice in turn."
        assert classify_answer_sentence(general, code_answer=False, problem_tokens=tokens) == "factual"

    @pytest.mark.parametrize("sentence", [
        "This approach runs in O(n) time and O(1) space.",
        "The function has a worst-case time complexity of O(n^2).",
        "It always uses constant space.",
        "A recursive reversal of a singly linked list also uses O(1) space, so recursion is an equally memory-efficient alternative.",
    ])
    def test_a_general_claim_is_never_set_aside(self, sentence):
        assert classify_answer_sentence(sentence, code_answer=True) in CHECKABLE

    def test_a_declarative_sentence_is_checked_whatever_its_verb(self):
        """The base classifier files a sentence under "inference" when its verb is not
        on a short list; in an answer key that left real assertions unchecked."""
        assert classify_claim("HAVING filters rows before grouping.") == "inference"
        assert classify_answer_sentence("HAVING filters rows before grouping.", code_answer=False) == "factual"
        assert classify_answer_sentence("Filters rows.", code_answer=False) == "inference"  # a fragment: too short to judge
        sentence = "HAVING filters rows before grouping, while WHERE filters groups after GROUP BY."
        assert classify_answer_sentence(sentence, code_answer=False) == "factual"
        # A marked conclusion, a fragment and a line of notation stay as they were.
        assert classify_answer_sentence("Therefore the scheduler picks the next process in the queue.", code_answer=False) == "inference"
        assert classify_answer_sentence("Unit tests for the user interface layer could include:", code_answer=False) == "inference"
        assert classify_answer_sentence("s(t+h) = 2t^2 + 4th + 2h^2 + 3t + 3h + 1.", code_answer=False) == "inference"

    def test_a_sentence_about_sql_is_not_masked_as_a_query(self):
        prose = "HAVING filters groups after GROUP BY, while WHERE filters rows before grouping."
        assert mask_code(prose) == prose
        assert mask_code("HAVING COUNT(*) > 1;").strip() == ""

    def test_factual_prose_in_a_descriptive_answer_stays_checkable(self):
        for sentence in (
            "Unit testing is the testing of a single function in isolation from the rest of the system.",
            "The scheduler uses a ready queue of processes.",
            "TCP reduces its congestion window when it detects packet loss.",
        ):
            assert classify_answer_sentence(sentence, code_answer=False) == "factual"


class TestCodeMasking:
    def test_markup_and_sql_are_code_not_prose(self):
        html = '<form action="/join" method="post">\n  <label for="email">Email</label>\n  <input type="email" id="email" required>\n</form>'
        assert mask_code(html).strip() == ""
        sql = "SELECT email, COUNT(*)\nFROM users\nGROUP BY email\nHAVING COUNT(*) > 1;"
        assert mask_code(sql).strip() == ""
        assert mask_code("select email from users where id > 3").strip() == ""

    def test_prose_that_starts_like_sql_is_kept(self):
        for prose in ("Select the best answer from the options below.", "Where a claim is unsupported it is flagged.",
                      "With recursion the call stack grows.", "Update the documentation after each release."):
            assert mask_code(prose) == prose

    def test_masking_keeps_every_offset(self):
        text = "Explain the query.\nSELECT email FROM users;\nThe answer is one row."
        assert len(mask_code(text)) == len(text)


class TestOnlyGeneratedCandidatesAreAffected:
    def test_free_text_sent_to_verify_is_classified_exactly_as_before(self):
        text = "Check if the number 37 is prime. Each member has an email address. This query groups the rows."
        assert [c.claim_type for c in extract_claims(text)] == [classify_claim(s) for s in
                                                               ("Check if the number 37 is prime.", "Each member has an email address.", "This query groups the rows.")]
        result = engine.verify_text(text, question="What does it do?", answer_text=text)
        assert all(c.claim_type not in {"instruction", "setup", "explanation"} for c in result.claims)

    def test_regions_are_split_at_the_end_of_the_question(self):
        question = "Each member has an email address. Find the duplicates."
        text = f"{question}\n\nEach member has an email address."
        claims = extract_claims(text, question_end=len(question))
        assert [c.claim_type for c in claims] == ["setup", "instruction", "factual"]


class TestVerifyCandidate:
    def _verify(self, question, answer):
        return engine.verify_candidate(make_candidate(question, answer_key=answer))

    def test_a_question_with_nothing_to_fact_check_is_not_unverifiable(self):
        rv = self._verify(
            "A music app stores its play queue as a singly linked list of track nodes. "
            "Implement a routine that reverses the queue so the last track plays first.",
            CODE_ONLY,
        )
        assert not any(c.claim_type in CHECKABLE for c in rv.claims)
        assert rv.verdict in ("trustworthy", "partially_reliable")
        assert rv.flagged_spans == [] and rv.contradictions == [] and rv.hallucination_probability == 0.0
        assert any("no independently checkable factual claims" in r for r in rv.reasons)
        assert decide(PS8_OK, rv).decision == "PASS"

    @pytest.mark.parametrize("question,answer", [
        # in the answer's prose
        ("Implement a routine that reverses a singly linked list.",
         CODE_ONLY + "\n\nA recursive reversal of a singly linked list also uses O(1) space, so recursion is an equally memory-efficient alternative."),
        # stated as a premise of the question
        ("A recursive reversal of a singly linked list uses O(1) space. Implement the recursive reversal.", CODE_ONLY),
        # tucked inside an instruction
        ("Implement a recursive reversal of a singly linked list, which uses O(1) space.", CODE_ONLY),
    ], ids=["answer-prose", "question-premise", "inside-instruction"])
    def test_a_false_claim_is_caught_wherever_it_sits(self, question, answer):
        rv = self._verify(question, answer)
        assert rv.contradictions and rv.verdict == "misleading"
        assert decide(PS8_OK, rv).decision == "REJECT"

    def test_a_general_claim_the_corpus_cannot_confirm_still_goes_to_review(self):
        rv = self._verify(
            "Implement a routine that reverses a singly linked list.",
            CODE_ONLY + "\n\nQuantum annealing always converges faster than simulated annealing.",
        )
        assert any(c.claim_type == "factual" for c in rv.claims)
        assert rv.verdict == "unverifiable" and decide(PS8_OK, rv).decision == "REVIEW"

    def test_a_fabricated_citation_is_still_flagged(self):
        rv = self._verify(
            "Implement a routine that reverses a singly linked list.",
            CODE_ONLY + "\n\nAccording to the 2019 Stanford Algorithms Report, this is 47.3% faster than recursion.",
        )
        assert any(c.claim_type == "citation" for c in rv.claims)
        assert any(s.claim_type == "fabrication_marker" for s in rv.flagged_spans)
        assert decide(PS8_OK, rv).decision != "PASS"

    def test_a_sql_answer_is_not_read_as_prose(self):
        rv = engine.verify_candidate(make_candidate(
            "A library keeps its members in a members table. Write a SQL query that lists every email address used by more than one member.",
            answer_key="SELECT email, COUNT(*)\nFROM members\nGROUP BY email\nHAVING COUNT(*) > 1;\n\nThis query groups the members by email and keeps the groups with more than one row.",
        ))
        assert [c.claim_type for c in rv.claims] == ["setup", "instruction", "explanation"]
        assert rv.verdict != "unverifiable" and decide(PS8_OK, rv).decision == "PASS"
