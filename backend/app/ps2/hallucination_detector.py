"""Hallucination Detector (PS2).

Estimates a hallucination probability from signals we can actually compute locally,
and returns the spans that drove the estimate. There is no trained hallucination
classifier here and we do not pretend otherwise: this is a transparent weighted
combination of four observable signals.

  1. Unsupported-claim rate  - claims the local corpus cannot ground.
  2. Contradictions          - internal self-conflict or conflict with the corpus.
  3. Fabrication markers     - invented citations, suspiciously precise statistics,
                               and overconfident absolutes, which are the textual
                               fingerprints of confabulation.
  4. Self-consistency        - optional resampling from Ollama; an answer the model
                               cannot reproduce under resampling is unstable.

Self-consistency is OFF by default (`settings.self_consistency_samples = 0`) because
each extra sample costs seconds against PS2's <10 s budget. Whether it ran is
reported in the result rather than assumed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from ..config import settings
from ..core.embeddings import embeddings
from ..core.ollama_client import OllamaUnavailable, ollama
from ..schemas import Claim, FlaggedSpan
from .response_analyzer import extract_citations

logger = logging.getLogger(__name__)

# Overconfident absolutes attached to a factual assertion.
_OVERCONFIDENT_RE = re.compile(
    r"\b(always|never|guaranteed|100% (?:accurate|correct|certain)|without (?:any )?exception|"
    r"in all cases|definitely|undoubtedly|it is impossible|no exceptions?)\b",
    re.I,
)

# Oddly precise statistics are a classic confabulation tell.
_PRECISE_STAT_RE = re.compile(
    r"\b\d{1,3}\.\d{1,2}\s*(?:%|percent\b)|\b\d{4,}\s*(?:times|x)\b", re.I
)

# Named-authority citation patterns that a question generator has no business inventing.
_INVENTED_CITATION_RE = re.compile(
    r"\b(?:[Aa]ccording to|[Aa]s (?:stated|defined|reported|shown) in)\s+(?:[Tt]he\s+)?"
    r"(?:(?:[A-Z][\w'-]+|\d{4})\s+){0,4}"
    r"(?:[Ss]tud(?:y|ies)|[Rr]eports?|[Pp]apers?|[Ss]tandards?|[Ss]pecifications?"
    r"|[Ss]urveys?|[Gg]uidelines?|[Jj]ournals?|[Rr]eviews?|[Ww]hitepapers?)\b",
)

# Weights for combining the signals into one probability. Configurable in one place.
_SIGNAL_WEIGHTS = {
    "unsupported": 0.45,
    "contradiction": 0.30,
    "fabrication_markers": 0.15,
    "self_inconsistency": 0.10,
}


@dataclass
class HallucinationResult:
    hallucination_probability: float
    flagged_spans: list[FlaggedSpan] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    signals: dict[str, float] = field(default_factory=dict)
    self_consistency_used: bool = False


def _fabrication_markers(text: str, claims: list[Claim]) -> list[tuple[str, str, str]]:
    """(span_text, reason, severity) for each textual fabrication marker found."""
    markers: list[tuple[str, str, str]] = []

    for m in _INVENTED_CITATION_RE.finditer(text):
        markers.append(
            (
                m.group(0),
                "references an external study, report or standard that cannot be "
                "verified against the local reference corpus - generated questions "
                "should not cite sources",
                "high",
            )
        )

    for m in _PRECISE_STAT_RE.finditer(text):
        markers.append(
            (
                m.group(0),
                "unusually precise statistic with no supporting source, a common "
                "signature of a fabricated figure",
                "medium",
            )
        )

    for claim in claims:
        if claim.claim_type not in {"factual", "answer", "inference"}:
            continue
        m = _OVERCONFIDENT_RE.search(claim.text)
        if m:
            markers.append(
                (
                    m.group(0),
                    "overconfident absolute in a factual statement; such claims are "
                    "rarely true without qualification",
                    "low",
                )
            )

    return markers


def _self_consistency_score(question: str, answer: str) -> tuple[float, bool]:
    """Resample the model and measure agreement with the original answer.

    Returns (agreement in [0,1], whether sampling actually ran). Any failure returns
    (1.0, False) - we must not penalise a candidate because Ollama was unavailable.
    """
    n = settings.self_consistency_samples
    if n <= 0 or not question.strip() or not answer.strip():
        return 1.0, False

    prompt = (
        "Answer the following question as concisely and factually as you can.\n\n"
        f"QUESTION:\n{question}\n\n"
        'Return only JSON: {"answer": "your answer"}'
    )

    samples: list[str] = []
    for _ in range(n):
        try:
            raw = ollama.generate(
                prompt,
                temperature=0.7,
                timeout_s=settings.self_consistency_timeout_s,
                max_tokens=220,
            )
        except OllamaUnavailable as exc:
            logger.warning("Self-consistency sampling skipped: %s", exc)
            return 1.0, False

        from ..ps8.candidate_builder import extract_json_object

        parsed, _ = extract_json_object(raw)
        text = (parsed or {}).get("answer") if isinstance(parsed, dict) else None
        samples.append(str(text) if text else raw)

    samples = [s for s in samples if s and s.strip()]
    if not samples:
        return 1.0, False

    scores = embeddings.similarity_matrix([answer], samples)[0]
    return float(sum(scores) / len(scores)), True


def detect(
    text: str,
    claims: list[Claim],
    verifications,
    contradictions: list[dict],
    *,
    question: str | None = None,
    answer: str | None = None,
) -> HallucinationResult:
    """Combine the four signals into a hallucination probability plus flagged spans."""
    spans: list[FlaggedSpan] = []
    reasons: list[str] = []

    # ---- Signal 1: unsupported claims -------------------------------
    checkable = [v for v in verifications if v.claim.claim_type in {"factual", "answer", "citation"}]
    unsupported = [v for v in checkable if v.status == "unsupported"]
    partial = [v for v in checkable if v.status == "partially_supported"]

    if checkable:
        # Partially-supported claims count as half-weight evidence gaps.
        unsupported_rate = (len(unsupported) + 0.5 * len(partial)) / len(checkable)
    else:
        unsupported_rate = 0.0

    for v in unsupported:
        spans.append(
            FlaggedSpan(
                text=v.claim.text,
                reason=f"unsupported claim: {v.detail}",
                start=v.claim.start,
                end=v.claim.end,
                severity="medium",
                claim_type=v.claim.claim_type,
                best_evidence=(v.entry.text[:220] if v.entry else None),
                best_similarity=v.similarity,
            )
        )
    for v in partial:
        spans.append(
            FlaggedSpan(
                text=v.claim.text,
                reason=f"only partially supported: {v.detail}",
                start=v.claim.start,
                end=v.claim.end,
                severity="low",
                claim_type=v.claim.claim_type,
                best_evidence=(v.entry.text[:220] if v.entry else None),
                best_similarity=v.similarity,
            )
        )

    if unsupported:
        reasons.append(
            f"{len(unsupported)} of {len(checkable)} checkable claims could not be "
            "grounded in the local reference corpus"
        )
    if partial:
        reasons.append(
            f"{len(partial)} claim(s) matched the corpus topically but their specific "
            "details were not confirmed"
        )

    # ---- Signal 2: contradictions -----------------------------------
    contradiction_signal = min(1.0, len(contradictions) * 0.5)
    for c in contradictions:
        span_a = c.get("span_a") or [None, None]
        spans.append(
            FlaggedSpan(
                text=c.get("claim_a", ""),
                reason=c.get("reason", "contradiction detected"),
                start=span_a[0],
                end=span_a[1],
                severity="high",
                claim_type="contradiction",
                best_evidence=c.get("claim_b"),
                best_similarity=c.get("similarity"),
            )
        )
    if contradictions:
        reasons.append(f"{len(contradictions)} contradiction(s) detected")

    # ---- Signal 3: fabrication markers ------------------------------
    markers = _fabrication_markers(text, claims)
    marker_signal = min(1.0, len(markers) * 0.34)
    for span_text, reason, severity in markers:
        from ..core.text_utils import find_span

        loc = find_span(text, span_text)
        spans.append(
            FlaggedSpan(
                text=span_text,
                reason=reason,
                start=loc[0] if loc else None,
                end=loc[1] if loc else None,
                severity=severity,  # type: ignore[arg-type]
                claim_type="fabrication_marker",
            )
        )
    if markers:
        reasons.append(f"{len(markers)} fabrication marker(s) found in the text")

    citations = extract_citations(text)
    if citations:
        reasons.append(
            f"{len(citations)} citation-like reference(s) present; citations in "
            "generated content cannot be verified against the local corpus"
        )

    # ---- Signal 4: self-consistency ---------------------------------
    agreement, sampling_used = _self_consistency_score(question or "", answer or "")
    self_inconsistency = 0.0
    if sampling_used:
        if agreement < settings.self_consistency_min_agreement:
            self_inconsistency = min(1.0, (settings.self_consistency_min_agreement - agreement) * 2)
            reasons.append(
                f"self-consistency check: resampling the model agreed with the given "
                f"answer only {agreement:.2f} (threshold "
                f"{settings.self_consistency_min_agreement:.2f})"
            )

    # ---- Combine ----------------------------------------------------
    signals = {
        "unsupported": round(unsupported_rate, 4),
        "contradiction": round(contradiction_signal, 4),
        "fabrication_markers": round(marker_signal, 4),
        "self_inconsistency": round(self_inconsistency, 4),
    }
    probability = sum(_SIGNAL_WEIGHTS[k] * v for k, v in signals.items())
    probability = round(max(0.0, min(1.0, probability)), 4)

    # Order spans so the UI shows the most serious first.
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    spans.sort(key=lambda s: severity_rank.get(s.severity, 3))

    return HallucinationResult(
        hallucination_probability=probability,
        flagged_spans=spans,
        reasons=reasons,
        signals={**signals, "self_consistency_agreement": round(agreement, 4)},
        self_consistency_used=sampling_used,
    )
