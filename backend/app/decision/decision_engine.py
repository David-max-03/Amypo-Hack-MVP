"""Decision Engine.

A candidate PASSes only when BOTH gates agree:

    PS8 structural validation passed
        AND
    PS2 reliability requirements met

Anything else is REVIEW (a human should look) or REJECT (send the combined feedback
back into regeneration). The split between the two matters: REJECT means "we know
this is wrong", REVIEW means "we cannot confirm this is right" - and per the
technical documentation, missing evidence must produce REVIEW, never REJECT.
"""

from __future__ import annotations

from ..config import settings
from ..schemas import DecisionResult, ReliabilityVerification, StructuralValidation

# Verdicts that indicate the content is actively wrong rather than merely unconfirmed.
_HARD_FAIL_VERDICTS = {"fabricated", "misleading"}
# Verdicts that mean "we could not confirm" - these route to review.
_SOFT_FAIL_VERDICTS = {"unverifiable"}


def decide(
    structural: StructuralValidation | None,
    reliability: ReliabilityVerification | None,
) -> DecisionResult:
    """Combine both gates into PASS / REVIEW / REJECT with explicit reasons."""
    reasons: list[str] = []

    # ---- Gate 1: PS8 structural ------------------------------------
    structural_ok = bool(structural and structural.passed)
    if structural is None:
        reasons.append("REJECT: structural validation did not run")
    elif not structural.passed:
        reasons.extend(f"PS8 structural failure: {r}" for r in structural.reasons)

    # A structural failure is a definite defect: we measured a duplicate, a
    # difficulty mismatch or concept drift. Reject and regenerate.
    if structural is not None and not structural.passed:
        return DecisionResult(
            decision="REJECT",
            reasons=reasons,
            structural_validation=structural,
            reliability_verification=reliability,
        )

    # ---- Gate 2: PS2 reliability -----------------------------------
    if reliability is None:
        return DecisionResult(
            decision="REVIEW",
            reasons=reasons + ["REVIEW: reliability verification did not run"],
            structural_validation=structural,
            reliability_verification=None,
        )

    score = reliability.reliability_score
    hallucination = reliability.hallucination_probability
    verdict = reliability.verdict

    # Actively wrong content: reject so the regeneration loop can fix it.
    if verdict in _HARD_FAIL_VERDICTS:
        reasons.append(
            f"PS2 verdict '{verdict}': the content conflicts with the reference corpus "
            "or is largely ungrounded"
        )
        reasons.extend(f"PS2: {r}" for r in reliability.reasons[:3])
        return DecisionResult(
            decision="REJECT",
            reasons=reasons,
            structural_validation=structural,
            reliability_verification=reliability,
        )

    # Unconfirmable content: a human decides, we do not guess.
    if verdict in _SOFT_FAIL_VERDICTS:
        reasons.append(
            f"PS2 verdict '{verdict}': the local reference corpus holds no evidence "
            "either way, so this needs human review rather than automatic rejection"
        )
        return DecisionResult(
            decision="REVIEW",
            reasons=reasons,
            structural_validation=structural,
            reliability_verification=reliability,
        )

    if hallucination > settings.pass_max_hallucination_probability:
        reasons.append(
            f"hallucination probability {hallucination:.2f} exceeds the pass ceiling "
            f"of {settings.pass_max_hallucination_probability:.2f}"
        )
        return DecisionResult(
            decision="REVIEW",
            reasons=reasons,
            structural_validation=structural,
            reliability_verification=reliability,
        )

    if score >= settings.pass_reliability_min and structural_ok:
        reasons.append(
            f"PASS: structural validation passed and reliability {score:.2f} >= "
            f"{settings.pass_reliability_min:.2f} (verdict '{verdict}')"
        )
        return DecisionResult(
            decision="PASS",
            reasons=reasons,
            structural_validation=structural,
            reliability_verification=reliability,
        )

    if score >= settings.review_reliability_min:
        reasons.append(
            f"REVIEW: reliability {score:.2f} sits between the review floor "
            f"{settings.review_reliability_min:.2f} and the pass threshold "
            f"{settings.pass_reliability_min:.2f}"
        )
        if reliability.flagged_spans:
            reasons.append(
                f"{len(reliability.flagged_spans)} flagged span(s) need a human check"
            )
        return DecisionResult(
            decision="REVIEW",
            reasons=reasons,
            structural_validation=structural,
            reliability_verification=reliability,
        )

    reasons.append(
        f"REJECT: reliability {score:.2f} is below the review floor of "
        f"{settings.review_reliability_min:.2f}"
    )
    return DecisionResult(
        decision="REJECT",
        reasons=reasons,
        structural_validation=structural,
        reliability_verification=reliability,
    )


def combined_feedback(
    structural: StructuralValidation | None, reliability: ReliabilityVerification | None
) -> tuple[list[str], list[str], list[dict]]:
    """Split the failure evidence into the three inputs the prompt builder needs."""
    structural_reasons = list(structural.reasons) if structural else []
    reliability_reasons = list(reliability.reasons) if reliability else []
    flagged_spans = (
        [
            {"text": s.text, "reason": s.reason, "severity": s.severity}
            for s in reliability.flagged_spans
        ]
        if reliability
        else []
    )
    return structural_reasons, reliability_reasons, flagged_spans
