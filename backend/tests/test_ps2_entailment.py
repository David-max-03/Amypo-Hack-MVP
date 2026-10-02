"""PS2 source grounding by entailment.

"Supported" used to mean the corpus has a sentence about the same thing in the same
words. That cannot tell a statement from its opposite, and with a corpus that covers
more than one topic it passed plainly wrong statements. These tests pin what
"supported" and "contradicted" mean now, on statements across the domains the corpus
covers - including the cases the check is known to get wrong.
"""

from __future__ import annotations

import json

import pytest

from backend.app.config import settings
from backend.app.core.entailment import entailment
from backend.app.decision.decision_engine import decide
from backend.app.ps2 import contradiction, engine, source_verification
from backend.app.ps2.response_analyzer import extract_claims
from backend.app.schemas import Claim
from backend.tests.conftest import REPO_ROOT, make_candidate
from backend.tests.test_ps2_question_claims import PS8_OK

QUESTION = "Explain the concept and state its key properties."

pytestmark = pytest.mark.skipif(
    not entailment.available, reason="the local entailment model is not installed"
)


@pytest.fixture(scope="module", autouse=True)
def _warm():
    from backend.app.core.embeddings import embeddings

    embeddings.warm_up()
    entailment.warm_up()


def _status(statement: str) -> str:
    claim = Claim(text=statement, claim_type="factual", start=0, end=len(statement))
    return source_verification.verify_claim(claim, domain="programming").status


def _decision(statement: str) -> str:
    rv = engine.verify_candidate(make_candidate(QUESTION, answer_key=statement, question_type="descriptive"))
    return decide(PS8_OK, rv).decision


# Correct statements the corpus covers.
RIGHT = [
    "Binary search runs in O(log n) time on a sorted array.",
    "Quicksort runs in O(n^2) time in the worst case.",
    "A stack is a last-in, first-out data structure.",
    "A queue is a first-in, first-out data structure.",
    "TCP is a connection-oriented protocol that provides reliable delivery.",
    "UDP is a connectionless protocol.",
    "In congestion avoidance the congestion window increases linearly by about one segment per round-trip time.",
    "A deadlock can occur only if mutual exclusion, hold and wait, no preemption and circular wait all hold.",
    "The k-nearest neighbours algorithm assigns the class that is most common among the k closest training points.",
    "Overfitting is when a model performs well on training data but poorly on unseen data.",
    "Regularisation reduces overfitting by adding a penalty on the size of the weights.",
    "Classification predicts a discrete class label and regression predicts a continuous value.",
    "Unit testing is the testing of a single function or class in isolation.",
    "A git rebase is an operation that rewrites history and produces a linear history.",
    "A prime number is an integer greater than 1 that has no positive divisors other than 1 and itself.",
    "An IPv4 address is 32 bits long.",
    "Symmetric encryption uses the same key to encrypt and decrypt.",
]

# The same statements made wrong. None may be marked "supported".
WRONG = [
    "Binary search runs in O(n) time on a sorted array.",
    "Merge sort runs in O(n^2) time in the worst case.",
    "Quicksort runs in O(n log n) time in the worst case.",
    "A stack is a first-in, first-out data structure.",
    "A queue is a last-in, first-out data structure.",
    "TCP is a connectionless protocol.",
    "UDP is a connection-oriented protocol that provides reliable delivery.",
    "In TCP slow start the congestion window is halved every round-trip time.",
    "In congestion avoidance the congestion window increases exponentially.",
    "A deadlock can occur if any one of the four conditions holds.",
    "Round-robin scheduling is non-preemptive.",
    "HAVING filters rows before grouping, while WHERE filters groups after GROUP BY.",
    "The k-nearest neighbours algorithm assigns the class of the single farthest training point.",
    "Overfitting is when a model performs poorly on training data but well on unseen data.",
    "Regularisation increases overfitting by removing the penalty on the weights.",
    "Unit testing is the testing of the complete integrated system.",
    "A git merge is an operation that rewrites history and produces a linear history.",
    "A prime number is an integer that has exactly three positive divisors.",
    "The derivative of a constant is 1.",
    "An IPv4 address is 128 bits long.",
    "Symmetric encryption uses a public key to encrypt and a private key to decrypt.",
]


class TestSupportMeansEntailment:
    @pytest.mark.parametrize("statement", RIGHT)
    def test_a_correct_statement_is_confirmed(self, temp_data_dir, statement):
        assert _status(statement) == "supported"
        assert _decision(statement) == "PASS"

    @pytest.mark.parametrize("statement", WRONG)
    def test_a_wrong_statement_is_never_confirmed(self, temp_data_dir, statement):
        assert _status(statement) in ("contradicted", "partially_supported", "unsupported")
        assert _decision(statement) != "PASS"

    def test_most_wrong_statements_are_called_wrong_not_just_unconfirmed(self, temp_data_dir):
        rejected = sum(_decision(s) == "REJECT" for s in WRONG)
        assert rejected >= 15, f"only {rejected} of {len(WRONG)} wrong statements were rejected"

    def test_the_evidence_is_the_sentence_that_was_read(self, temp_data_dir):
        claim = Claim(text="A stack is a last-in, first-out data structure.", claim_type="factual", start=0, end=10)
        v = source_verification.verify_claim(claim, domain="programming")
        assert v.judged_by == "entailment" and "last-in, first-out" in v.evidence_sentence
        assert "entailed by" in v.detail

    def test_same_numbers_and_complexities_are_required(self, temp_data_dir):
        # The model alone reads "32 bits" and "128 bits" as near-equivalent.
        assert _status("An IPv4 address is 32 bits long.") == "supported"
        assert _status("An IPv4 address is 128 bits long.") != "supported"
        assert _status("Recursive binary search uses O(n) stack space.") == "contradicted"

    def test_a_claim_outside_the_corpus_is_unsupported_not_wrong(self, temp_data_dir):
        statement = "A Bloom filter is a probabilistic data structure that never reports false negatives."
        assert _status(statement) in ("unsupported", "partially_supported")
        assert _decision(statement) == "REVIEW"

    def test_the_support_threshold_setting_still_applies(self, temp_data_dir, monkeypatch):
        paraphrase = "Regularisation reduces overfitting by adding a penalty on the size of the weights."
        assert _status(paraphrase) == "supported"
        monkeypatch.setattr(settings, "claim_support_threshold", 0.99)
        assert _status(paraphrase) != "supported"


class TestKnownLimits:
    """Documented behaviour, not goals."""

    def test_attributes_swapped_between_two_concepts_are_not_detected(self, temp_data_dir):
        # The small model reads this as agreeing with the entry that says the reverse.
        swapped = "Classification predicts a continuous value and regression predicts a discrete class label."
        assert _status(swapped) == "supported"

    def test_a_two_part_statement_may_only_be_partly_confirmed(self, temp_data_dir):
        both = "Merge sort runs in O(n log n) time in the worst case and is a stable sort."
        assert _status(both) in ("supported", "partially_supported")


class TestContradictionsNeedTheRightSentence:
    @pytest.mark.parametrize("statement", [
        "Unit testing involves testing individual components in isolation to ensure they work as expected.",
        "Unit testing would involve testing each individual function in isolation to ensure that it performs its intended task correctly.",
        "Git merge combines the changes from one branch into another, creating a new merge commit that marks the point where the two branches were combined.",
        "In TCP congestion avoidance the congestion window grows linearly.",
    ])
    def test_a_correct_statement_is_not_contradicted_by_a_neighbouring_sentence(self, temp_data_dir, statement):
        assert _status(statement) != "contradicted"
        assert _decision(statement) != "REJECT"

    def test_word_level_negation_must_be_confirmed(self, temp_data_dir):
        """ "checks its cache" / "if not found in the cache, queries ..." is not a self-contradiction."""
        text = ("The DNS server checks its cache for the IP address. "
                "If not found in the cache, the DNS server queries its authoritative nameservers for the IP address.")
        assert contradiction.find_internal_contradictions(extract_claims(text)) == []

    def test_a_real_self_contradiction_is_still_found(self, temp_data_dir):
        text = "Binary search runs in O(log n) time on a sorted array. Binary search runs in O(n) time on a sorted array."
        assert contradiction.find_internal_contradictions(extract_claims(text))

    def test_average_and_worst_case_are_not_in_conflict(self):
        assert contradiction.complexity_conflict(
            "Quicksort runs in O(n^2) time in the worst case.", "Quicksort runs in O(n log n) time on average."
        ) is None
        assert contradiction.complexity_conflict(
            "Quicksort runs in O(n) time in the worst case.", "Quicksort runs in O(n^2) time in the worst case."
        ) is not None


class TestInstructionsAssertNothing:
    def test_polarity_and_antonym_rules_do_not_apply_to_an_instruction(self, temp_data_dir):
        rv = engine.verify_candidate(make_candidate(
            "A catalogue stores product IDs in ascending order. Implement the binary search iteratively.",
            answer_key="def search(a, t):\n    lo, hi = 0, len(a) - 1\n    while lo <= hi:\n        mid = (lo + hi) // 2\n        if a[mid] == t:\n            return mid\n        lo, hi = (mid + 1, hi) if a[mid] < t else (lo, mid - 1)\n    return -1",
        ))
        assert rv.contradictions == [] and decide(PS8_OK, rv).decision == "PASS"

    def test_a_wrong_complexity_is_caught_even_inside_an_instruction(self, temp_data_dir):
        rv = engine.verify_candidate(make_candidate(
            "Implement a recursive reversal of a singly linked list, which uses O(1) space.",
            answer_key="def reverse(head):\n    return head",
        ))
        assert rv.contradictions and decide(PS8_OK, rv).decision == "REJECT"


class TestFallbackWithoutTheModel:
    def test_similarity_rule_is_used_and_reported(self, temp_data_dir, monkeypatch):
        monkeypatch.setattr(entailment, "_state", "unavailable")
        assert not entailment.available and "fallback" in entailment.backend
        claim = Claim(text="A stack is a last-in, first-out data structure.", claim_type="factual", start=0, end=10)
        v = source_verification.verify_claim(claim, domain="programming")
        assert v.judged_by == "similarity" and v.status == "supported"

    def test_health_reports_the_entailment_backend(self, temp_data_dir):
        from fastapi.testclient import TestClient

        from backend.app.main import app

        info = TestClient(app).get("/api/v1/health").json()["embeddings"]["entailment"]
        assert info["available"] is True and info["configured_model"] == settings.entailment_model


class TestReferenceCorpus:
    @pytest.fixture(scope="class")
    def entries(self):
        return json.loads((REPO_ROOT / "data" / "reference_corpus.json").read_text())

    def test_every_entry_is_complete_and_unique(self, entries):
        items = entries["entries"]
        assert entries["entry_count"] == len(items) >= 150
        assert len({e["id"] for e in items}) == len(items)
        for e in items:
            assert e["title"] and e["text"] and e["domain"] and e["source"], e["id"]

    def test_the_corpus_reaches_beyond_linked_lists(self, entries):
        text = " ".join(e["title"].lower() for e in entries["entries"])
        for topic in ("binary search", "sql", "deadlock", "tcp", "k-nearest", "unit testing",
                      "html form", "git", "encryption", "cap theorem", "derivative", "prime"):
            assert topic in text, topic

    def test_sentences_name_their_subject(self, entries):
        """Clause-by-clause checks cannot use "It runs in O(log n) time"."""
        import re

        new = [e for e in entries["entries"] if not re.match(r"(prog|math|sci|health|biz|lang|gk)-\\d", e["id"])]
        assert len(new) >= 100
        offenders = [e["id"] for e in new if re.search(r"(?:^|\\. )(?:It|Its|They|This) ", e["text"])]
        assert offenders == []


class TestAnswerThatRejectsItsOwnResult:
    Q = ("Given the function h(x) = 5x^3 - 2x^2 + 4x + 1, find the derivative of h(x) and explain any "
         "errors in the following proposed solution: h'(x) = 15x^2 - 4x + 4.")

    def _verify(self, answer):
        return engine.verify_candidate(make_candidate(self.Q, answer_key=answer, question_type="numerical", domain="mathematics"))

    def test_calling_a_result_wrong_then_giving_it_as_the_fix_is_a_contradiction(self, temp_data_dir):
        rv = self._verify("h'(x) = 15x^2 - 4x + 4 is incorrect. The correct derivative is h'(x) = 15x^2 - 4x + 4.")
        assert rv.contradictions and "gives the same result as the correction" in rv.contradictions[0]["reason"]
        assert decide(PS8_OK, rv).decision == "REJECT"

    @pytest.mark.parametrize("answer", [
        "h'(x) = 15x^2 - 4x is incorrect. The correct derivative is h'(x) = 15x^2 - 4x + 4.",
        "The proposed solution is correct: h'(x) = 15x^2 - 4x + 4.",
    ])
    def test_a_real_correction_or_a_confirmation_is_not(self, temp_data_dir, answer):
        assert self._verify(answer).contradictions == []
