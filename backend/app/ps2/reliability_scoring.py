"""Reliability Scoring Engine (PS2).

Aggregates every PS2 signal into a single reliability score in [0,1] plus one of the
five verdicts the problem statement defines. All weights live in `settings` so the
trust policy is tunable in exactly one place.

The score is a weighted sum of five sub-scores, each expressed so that higher is
always better:

  source_grounding    - share of checkable claims the corpus actually supports
  non_hallucination   - 1 - hallucination_probability
  factual_consistency - how well the claims agree with their matched evidence
  non_contradiction   - penalty for internal or external conflicts
  answer_completeness - whether the answer is substantive rather than a stub
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import settings
from ..schemas import Claim


@dataclass
class ScoringResult:
    reliability_score: float
    confidence_score: float
    verdict: str
    signals: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


def _source_grounding(verifications) -> tuple[float, int, int]:
    """Supported share of checkable claims, plus (supported, checkable) counts."""
    checkable = [
        v for v in verifications if v.claim.claim_type in {"factual", "answer", "citation"}
    ]
    if not checkable:
        # Nothing to ground. Neutral, not good: expressed as 0.5 so a response made
        # entirely of opinions cannot score as "trustworthy" on grounding alone.
        return 0.5, 0, 0

    supported = sum(1 for v in checkable if v.status == "supported")
    partial = sum(1 for v in checkable if v.status == "partially_supported")
    return (supported + 0.5 * partial) / len(checkable), supported, len(checkable)


def _factual_consistency(verifications) -> float:
    """Mean agreement between each checkable claim and its best evidence.

    Uses the combined semantic + lexical signal so a claim that merely sounds like
    the evidence does not score as consistent with it.
    """
    checkable = [
        v for v in verifications if v.claim.claim_type in {"factual", "answer", "citation"}
    ]
    if not checkable:
        return 0.5
    total = sum(0.6 * v.similarity + 0.4 * v.keyword_grounding for v in checkable)
    return total / len(checkable)


def _answer_completeness(answer_text: str | None) -> float:
    """Is the answer substantive? A one-word stub is not a usable answer key."""
    if answer_text is None:
        return 0.5  # not applicable to this request
    text = answer_text.strip()
    if not text:
        return 0.0
    words = len(text.split())
    if words < 3:
        return 0.2
    if words < 8:
        return 0.6
    if words < 20:
        return 0.85
    return 1.0


def score(
    verifications,
    contradictions: list[dict],
    hallucination_probability: float,
    *,
    claims: list[Claim] | None = None,
    answer_text: str | None = None,
) -> ScoringResult:
    """Produce the reliability score, confidence and verdict."""
    grounding, supported_count, checkable_count = _source_grounding(verifications)
    consistency = _factual_consistency(verifications)
    non_hallucination = 1.0 - hallucination_probability
    # Each contradiction is a serious trust failure, so the penalty is steep.
    non_contradiction = max(0.0, 1.0 - 0.4 * len(contradictions))
    completeness = _answer_completeness(answer_text)

    sub_scores = {
        "source_grounding": grounding,
        "non_hallucination": non_hallucination,
        "factual_consistency": consistency,
        "non_contradiction": non_contradiction,
        "answer_completeness": completeness,
    }

    weights = settings.reliability_weights
    reliability = sum(weights[k] * v for k, v in sub_scores.items())
    reliability = round(max(0.0, min(1.0, reliability)), 4)

    # A detected contradiction is a definite trust failure. It caps the score itself
    # below the partially-reliable band, so the verdict (read from the score bands
    # below) and the score can never disagree - previously a contradicted response
    # was labelled "misleading" while still scoring 0.70-0.86.
    contradiction_capped = False
    if contradictions and reliability > contradiction_reliability_cap():
        reliability = contradiction_reliability_cap()
        contradiction_capped = True

    # Confidence is about how much evidence we had, not how good the answer was.
    # A verdict drawn from two claims deserves less confidence than one from ten.
    evidence_breadth = min(1.0, checkable_count / 5.0) if checkable_count else 0.2
    unverifiable_share = (
        1.0 - (supported_count / checkable_count) if checkable_count else 1.0
    )
    confidence = round(
        max(0.0, min(1.0, 0.5 * evidence_breadth + 0.5 * (1.0 - 0.6 * unverifiable_share))), 4
    )

    verdict = _classify(
        reliability=reliability,
        contradictions=contradictions,
        supported_count=supported_count,
        checkable_count=checkable_count,
        hallucination_probability=hallucination_probability,
    )

    reasons = _build_reasons(
        sub_scores, supported_count, checkable_count, contradictions, hallucination_probability
    )
    if contradiction_capped:
        reasons.insert(
            0,
            f"reliability capped at {reliability:.2f} because {len(contradictions)} "
            "contradiction(s) were detected - contradicted content cannot score as reliable",
        )
    recommendations = _build_recommendations(verdict, sub_scores, contradictions, checkable_count)

    return ScoringResult(
        reliability_score=reliability,
        confidence_score=confidence,
        verdict=verdict,
        signals={k: round(v, 4) for k, v in sub_scores.items()},
        reasons=reasons,
        recommendations=recommendations,
    )


def contradiction_reliability_cap() -> float:
    """Highest score a contradicted response may have: just inside the misleading band."""
    return round(settings.verdict_partially_reliable_min - 0.01, 4)


def verdict_for_score(reliability: float) -> str:
    """The one score -> verdict mapping, shared by scoring and by the tests."""
    if reliability >= settings.verdict_trustworthy_min:
        return "trustworthy"
    if reliability >= settings.verdict_partially_reliable_min:
        return "partially_reliable"
    if reliability >= settings.verdict_misleading_min:
        return "misleading"
    return "fabricated"


def _classify(
    *,
    reliability: float,
    contradictions: list[dict],
    supported_count: int,
    checkable_count: int,
    hallucination_probability: float,
) -> str:
    """Map the numbers onto one of PS2's five verdicts.

    "unverifiable" is checked before the low-score verdicts on purpose: a response we
    simply have no evidence about must not be labelled "fabricated". The technical
    documentation is explicit that an incomplete corpus is not proof of falsehood.
    """
    supported_ratio = (supported_count / checkable_count) if checkable_count else 0.0

    # Evidence-based exception: almost nothing could be grounded either way and nothing
    # conflicts, so the honest verdict is "unverifiable" (-> human review), not a
    # score band. Contradicted responses never take this path.
    if (
        not contradictions
        and checkable_count > 0
        and supported_ratio <= settings.unverifiable_max_supported_ratio
        and hallucination_probability < 0.6
    ):
        return "unverifiable"

    # Otherwise the verdict is read from the score alone. Contradictions have already
    # capped the score, so they land in "misleading" (or "fabricated") through here.
    return verdict_for_score(reliability)


def _build_reasons(
    sub_scores: dict[str, float],
    supported_count: int,
    checkable_count: int,
    contradictions: list[dict],
    hallucination_probability: float,
) -> list[str]:
    reasons: list[str] = []

    if checkable_count:
        reasons.append(
            f"{supported_count} of {checkable_count} checkable claims were grounded in "
            f"the local reference corpus (grounding score "
            f"{sub_scores['source_grounding']:.2f})"
        )
    else:
        reasons.append(
            "no independently checkable factual claims were found, so source grounding "
            "was scored neutrally"
        )

    reasons.append(f"estimated hallucination probability {hallucination_probability:.2f}")

    if contradictions:
        internal = sum(1 for c in contradictions if c.get("type") == "internal")
        external = len(contradictions) - internal
        parts = []
        if internal:
            parts.append(f"{internal} internal self-contradiction(s)")
        if external:
            parts.append(f"{external} conflict(s) with the reference corpus")
        reasons.append("; ".join(parts))

    if sub_scores["answer_completeness"] < 0.6:
        reasons.append("the answer is too short to be a complete answer key")

    return reasons


def _build_recommendations(
    verdict: str,
    sub_scores: dict[str, float],
    contradictions: list[dict],
    checkable_count: int,
) -> list[str]:
    recs: list[str] = []

    if verdict == "trustworthy":
        recs.append("Accept: the response met every reliability threshold.")
        return recs

    if contradictions:
        recs.append(
            "Resolve the contradictions listed in flagged_spans before using this "
            "content - the statements cannot all be correct."
        )
    if sub_scores["source_grounding"] < 0.5:
        recs.append(
            "Add or cite supporting evidence, or extend the local reference corpus to "
            "cover this topic, then re-verify."
        )
    if sub_scores["non_hallucination"] < 0.7:
        recs.append(
            "Remove unverifiable specifics - invented citations, precise statistics and "
            "absolute claims are the main drivers of the hallucination estimate."
        )
    if sub_scores["answer_completeness"] < 0.6:
        recs.append("Expand the answer so it fully addresses the question.")
    if verdict == "unverifiable" and checkable_count:
        recs.append(
            "Route to human review: the corpus has no evidence either way, so this is "
            "unconfirmed rather than wrong."
        )

    if not recs:
        recs.append("Route to human review before publishing.")
    return recs
