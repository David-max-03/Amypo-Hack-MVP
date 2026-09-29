"""Reliability Verification Engine (PS2) - the orchestrator.

Runs the full PS2 pipeline over one piece of text:

    Response Analyzer -> claim extraction
      -> Source Verification (local corpus, MiniLM + keyword grounding)
      -> Contradiction Detection (internal + external)
      -> Hallucination Detector
      -> Reliability Scoring
      -> Verdict + flagged spans + evidence

Every stage is timed because PS2 has a hard <10 s per-response budget, and the
measured total is returned to the caller rather than merely logged.
"""

from __future__ import annotations

import logging

from ..config import settings
from ..core.embeddings import embeddings
from ..core.timing import Stopwatch
from ..schemas import Candidate, ReliabilityVerification
from . import contradiction, hallucination_detector, reliability_scoring, source_verification
from .response_analyzer import extract_claims

logger = logging.getLogger(__name__)


def verify_text(
    text: str,
    *,
    source_context: list[str] | None = None,
    domain: str | None = None,
    question: str | None = None,
    answer_text: str | None = None,
) -> ReliabilityVerification:
    """Run the complete PS2 verification pipeline over one response."""
    watch = Stopwatch()

    with watch.stage("ps2.claim_extraction"):
        claims = extract_claims(text)

    with watch.stage("ps2.source_verification"):
        verifications = source_verification.verify_claims(
            claims, domain=domain, extra_context=source_context
        )

    with watch.stage("ps2.contradiction_detection"):
        contradictions = contradiction.find_internal_contradictions(
            claims
        ) + contradiction.find_external_contradictions(verifications)

    with watch.stage("ps2.hallucination_detection"):
        hallucination = hallucination_detector.detect(
            text,
            claims,
            verifications,
            contradictions,
            question=question,
            answer=answer_text,
        )

    with watch.stage("ps2.reliability_scoring"):
        scored = reliability_scoring.score(
            verifications,
            contradictions,
            hallucination.hallucination_probability,
            claims=claims,
            answer_text=answer_text,
        )

    reasons = [*scored.reasons, *hallucination.reasons]

    return ReliabilityVerification(
        reliability_score=scored.reliability_score,
        confidence_score=scored.confidence_score,
        hallucination_probability=hallucination.hallucination_probability,
        verdict=scored.verdict,  # type: ignore[arg-type]
        flagged_spans=hallucination.flagged_spans,
        evidence=source_verification.to_evidence(verifications),
        claims=claims,
        signals={**scored.signals, **hallucination.signals},
        contradictions=contradictions,
        reasons=reasons,
        recommendations=scored.recommendations,
        embedding_backend=embeddings.backend,
        self_consistency_used=hallucination.self_consistency_used,
        timings_ms=watch.as_dict(),
    )


def verify_candidate(candidate: Candidate) -> ReliabilityVerification:
    """Verify a generated PS8 candidate.

    The question and its answer key are verified together: a question can be fine
    while its answer key is wrong, and that combination is exactly what must not
    reach a learner.
    """
    combined = f"{candidate.question}\n\n{candidate.answer_key}".strip()
    return verify_text(
        combined,
        domain=candidate.domain,
        question=candidate.question,
        answer_text=candidate.answer_key,
    )


def within_budget(verification: ReliabilityVerification) -> bool:
    """Did this verification meet PS2's stated latency requirement?"""
    total_ms = verification.timings_ms.get("total_ms", 0.0)
    return total_ms <= settings.ps2_target_latency_s * 1000.0
