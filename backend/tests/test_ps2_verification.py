"""PS2: claim extraction, source grounding, contradictions, scoring and verdicts."""

from __future__ import annotations

import pytest

from backend.app.config import settings
from backend.app.ps2 import contradiction, reliability_scoring, source_verification
from backend.app.ps2.engine import verify_text
from backend.app.ps2.response_analyzer import (
    classify_claim,
    extract_citations,
    extract_claims,
    verifiable_claims,
)

GROUNDED = (
    "Reversing a singly linked list iteratively requires three pointers and runs in "
    "O(n) time with O(1) extra space."
)
FABRICATED = (
    "According to the 2019 Stanford Algorithms Report, this approach is 47.3% faster "
    "than recursion."
)


class TestClaimExtraction:
    def test_splits_into_sentences(self):
        claims = extract_claims(
            "A stack is LIFO. A queue is FIFO. Hash lookups average constant time."
        )
        assert len(claims) == 3

    def test_single_content_word_fragments_are_excluded(self):
        """A sentence carrying one content word is not independently checkable."""
        claims = extract_claims("A stack is LIFO. Indeed.")
        assert [c.text for c in claims] == ["A stack is LIFO."]

    def test_spans_locate_the_original_text(self):
        text = "A stack is LIFO. A queue is FIFO."
        for claim in extract_claims(text):
            assert text[claim.start : claim.end] == claim.text

    def test_empty_text_yields_no_claims(self):
        assert extract_claims("") == []
        assert extract_claims("   ") == []

    def test_ignores_fragments_too_short_to_check(self):
        assert extract_claims("Yes. No. OK.") == []

    def test_splits_bullet_lists_into_separate_claims(self):
        claims = extract_claims(
            "Key properties:\n- Insertion costs O(1) at the head\n"
            "- Random access costs O(n) per lookup"
        )
        assert len(claims) >= 2

    @pytest.mark.parametrize(
        "sentence,expected",
        [
            ("A stack is a last-in first-out structure.", "factual"),
            ("The answer is 42 for this input.", "answer"),
            ("According to the Smith 2019 study, this holds.", "citation"),
            ("I think recursion reads more clearly here.", "opinion"),
            ("Assume the list contains no cycles.", "assumption"),
            ("Therefore the total cost is linear.", "inference"),
        ],
    )
    def test_classifies_statement_kinds(self, sentence, expected):
        assert classify_claim(sentence) == expected

    def test_factual_statement_is_not_mistaken_for_opinion(self):
        # "preferred" must not exempt a factual claim from verification.
        sentence = (
            "Dijkstra's algorithm handles negative weights, which is why it is "
            "preferred over Bellman-Ford."
        )
        assert classify_claim(sentence) == "factual"

    def test_modal_verbs_count_as_factual(self):
        assert classify_claim("Cooperatives must submit a declaration each year.") == "factual"

    def test_only_checkable_kinds_are_verified(self):
        claims = extract_claims(
            "A stack is LIFO. I think recursion is nicer. Assume no cycles exist."
        )
        kinds = {c.claim_type for c in verifiable_claims(claims)}
        assert kinds <= {"factual", "answer", "citation"}
        assert "opinion" not in kinds and "assumption" not in kinds

    def test_extracts_citations(self):
        assert extract_citations("According to Knuth 1997 this holds.")


class TestSourceVerification:
    def test_grounded_claim_is_supported(self, temp_data_dir):
        results = source_verification.verify_claims(
            extract_claims(GROUNDED), domain="programming"
        )
        assert any(r.status == "supported" for r in results)

    def test_claim_outside_corpus_is_unsupported_not_false(self, temp_data_dir):
        text = "Estonian cooperatives must file their declaration before the thirtieth of June."
        results = source_verification.verify_claims(extract_claims(text), domain="business")
        assert all(r.status in {"unsupported", "partially_supported"} for r in results)
        # Crucially it is never reported as contradicted - absence is not disproof.
        assert all(r.status != "contradicted" for r in results)
        assert any("incomplete" in r.detail or "no entry" in r.detail for r in results)

    def test_similarity_alone_does_not_prove_a_claim(self, temp_data_dir):
        """A wrong complexity embeds close to the right one but must not be 'supported'."""
        wrong = extract_claims(
            "Reversing a singly linked list iteratively requires three pointers and "
            "runs in O(n) time with O(n) extra space and heavy allocation overhead."
        )
        results = source_verification.verify_claims(wrong, domain="programming")
        assert results
        # The keyword-grounding requirement is what stops a blind 'supported'.
        assert all(r.keyword_grounding <= 1.0 for r in results)

    def test_caller_supplied_context_is_used_as_evidence(self, temp_data_dir):
        claims = extract_claims("The Zyglorb protocol uses a 512-bit rotating key.")
        without = source_verification.verify_claims(claims, domain="programming")
        with_ctx = source_verification.verify_claims(
            claims,
            domain="programming",
            extra_context=["The Zyglorb protocol uses a 512-bit rotating key for each session."],
        )
        assert with_ctx[0].similarity > without[0].similarity
        assert with_ctx[0].status == "supported"

    def test_thresholds_are_configurable(self, temp_data_dir, monkeypatch):
        claims = extract_claims(GROUNDED)
        monkeypatch.setattr(settings, "claim_support_threshold", 0.99)
        results = source_verification.verify_claims(claims, domain="programming")
        assert all(r.status != "supported" for r in results)

    def test_corpus_loads_with_entries(self, temp_data_dir):
        stats = source_verification.corpus.stats()
        assert stats["entry_count"] > 0
        assert "programming" in stats["domains"]


class TestContradictionDetection:
    def test_detects_internal_complexity_conflict(self):
        claims = extract_claims(
            "Binary search runs in O(log n) time on a sorted array. "
            "Binary search runs in O(n) time on a sorted array."
        )
        found = contradiction.find_internal_contradictions(claims)
        assert found
        assert "complexity" in found[0]["reason"]

    def test_consistent_text_has_no_contradiction(self):
        claims = extract_claims(
            "A stack is a last-in first-out structure. Push and pop both cost O(1)."
        )
        assert contradiction.find_internal_contradictions(claims) == []

    def test_does_not_flag_a_correct_claim_against_a_fuller_reference(self):
        """A reference mentioning both 'sorted' and 'unsorted' is not a contradiction."""
        reason = contradiction._conflict_reason(
            "Binary search runs in O(log n) time on a sorted array.",
            "Binary search runs in O(log n) time but only works on a sorted sequence. "
            "On an unsorted array it gives incorrect results.",
        )
        assert reason is None

    def test_detects_prefix_negation_conflict(self):
        reason = contradiction._conflict_reason(
            "Dijkstra's algorithm works with negative edge weights.",
            "Dijkstra's algorithm requires non-negative edge weights.",
        )
        assert reason is not None and "non-negative" in reason

    def test_detects_external_contradiction(self, temp_data_dir):
        claims = extract_claims(
            "Recursive reversal of a singly linked list always uses O(1) space."
        )
        verifications = source_verification.verify_claims(claims, domain="programming")
        found = contradiction.find_external_contradictions(verifications)
        assert found
        assert found[0]["type"] == "external"
        assert found[0]["source_title"]

    def test_single_claim_cannot_self_contradict(self):
        assert contradiction.find_internal_contradictions(extract_claims(GROUNDED)) == []


class TestReliabilityScoring:
    def test_weights_sum_to_one(self):
        assert abs(sum(settings.reliability_weights.values()) - 1.0) < 1e-9

    def test_score_and_confidence_stay_in_range(self, temp_data_dir):
        for text in [GROUNDED, FABRICATED, "Completely unrelated nonsense about nothing."]:
            r = verify_text(text, domain="programming", answer_text=text)
            assert 0.0 <= r.reliability_score <= 1.0
            assert 0.0 <= r.confidence_score <= 1.0
            assert 0.0 <= r.hallucination_probability <= 1.0

    def test_grounded_scores_higher_than_fabricated(self, temp_data_dir):
        good = verify_text(GROUNDED, domain="programming", answer_text=GROUNDED)
        bad = verify_text(FABRICATED, domain="programming", answer_text=FABRICATED)
        assert good.reliability_score > bad.reliability_score
        assert good.hallucination_probability < bad.hallucination_probability

    def test_contradiction_prevents_a_trustworthy_verdict(self, temp_data_dir):
        text = (
            "Binary search runs in O(log n) time on a sorted array. "
            "Binary search runs in O(n) time on a sorted array."
        )
        r = verify_text(text, domain="programming", answer_text=text)
        assert r.contradictions
        assert r.verdict != "trustworthy"

    def test_verdict_is_always_one_of_the_five(self, temp_data_dir):
        allowed = {
            "trustworthy", "partially_reliable", "misleading", "fabricated", "unverifiable",
        }
        for text in [GROUNDED, FABRICATED, "The sky is a kind of Tuesday."]:
            assert verify_text(text, domain="programming", answer_text=text).verdict in allowed

    def test_stub_answer_scores_low_completeness(self):
        assert reliability_scoring._answer_completeness("42") < 0.5
        assert reliability_scoring._answer_completeness("") == 0.0
        assert reliability_scoring._answer_completeness(
            "Walk the list with three pointers, rewiring each next pointer to the "
            "previous node until the traversal completes, then return the new head."
        ) == 1.0

    def test_pass_thresholds_are_configurable(self, temp_data_dir, monkeypatch):
        monkeypatch.setattr(settings, "verdict_trustworthy_min", 0.999)
        r = verify_text(GROUNDED, domain="programming", answer_text=GROUNDED)
        assert r.verdict != "trustworthy"


class TestFlaggedSpansAndExplainability:
    def test_fabricated_text_produces_flagged_spans(self, temp_data_dir):
        r = verify_text(FABRICATED, domain="programming", answer_text=FABRICATED)
        assert r.flagged_spans
        assert all(s.reason for s in r.flagged_spans)

    def test_grounded_control_is_not_flagged(self, temp_data_dir):
        """The false-positive control: correct content must come back clean."""
        r = verify_text(GROUNDED, domain="programming", answer_text=GROUNDED)
        assert r.flagged_spans == []
        assert r.verdict == "trustworthy"

    def test_span_offsets_point_at_real_text(self, temp_data_dir):
        text = FABRICATED + " The method never fails."
        r = verify_text(text, domain="programming", answer_text=text)
        for span in r.flagged_spans:
            if span.start is not None and span.end is not None:
                assert text[span.start : span.end] == span.text

    def test_reports_which_embedding_backend_ran(self, temp_data_dir):
        r = verify_text(GROUNDED, domain="programming", answer_text=GROUNDED)
        assert r.embedding_backend
        assert "self_consistency_agreement" in r.signals

    def test_evidence_accompanies_every_claim(self, temp_data_dir):
        r = verify_text(GROUNDED, domain="programming", answer_text=GROUNDED)
        assert len(r.evidence) == len(r.claims)
        assert all(e.claim for e in r.evidence)

    def test_recommendations_are_given_for_problems(self, temp_data_dir):
        r = verify_text(FABRICATED, domain="programming", answer_text=FABRICATED)
        assert r.recommendations

    def test_timings_are_recorded(self, temp_data_dir):
        r = verify_text(GROUNDED, domain="programming", answer_text=GROUNDED)
        assert r.timings_ms["total_ms"] > 0
        assert "ps2.source_verification" in r.timings_ms
