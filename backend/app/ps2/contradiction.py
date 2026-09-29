"""Contradiction Detection Module (PS2).

Detects two distinct kinds of conflict, both of which PS2 requires:

  1. INTERNAL  - the response contradicts itself (two claims that are semantically
     about the same thing but assert opposite or incompatible values).
  2. EXTERNAL  - a claim contradicts the trusted reference corpus.

The technique is deliberately explainable rather than a black box: we look for
claim pairs that are highly similar (same subject) yet differ on a polarity marker,
a numeric value, or a mutually exclusive term from a known antonym group. Judges can
read the reason and see exactly why something was flagged.
"""

from __future__ import annotations

import re
from typing import Any

from ..core.embeddings import embeddings
from ..core.text_utils import normalize
from ..schemas import Claim

# Pairs of terms that cannot both be true of the same subject.
_ANTONYM_GROUPS: list[set[str]] = [
    {"always", "never"},
    {"increases", "decreases"},
    {"faster", "slower"},
    {"higher", "lower"},
    {"more", "fewer"},
    {"true", "false"},
    {"sorted", "unsorted"},
    {"mutable", "immutable"},
    {"synchronous", "asynchronous"},
    {"stable", "unstable"},
    {"required", "optional"},
    {"supported", "unsupported"},
    {"lifo", "fifo"},
    {"ascending", "descending"},
]

_NEGATION_RE = re.compile(
    r"\b(not|never|no|cannot|can't|doesn't|does not|isn't|is not|won't|will not|"
    r"aren't|are not|without)\b",
    re.I,
)

# Big-O complexity claims - the single most common place a generated answer is wrong.
_COMPLEXITY_RE = re.compile(r"o\(\s*([^)]{1,20}?)\s*\)", re.I)

_NUMBER_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(%|percent|seconds?|ms|minutes?|hours?|"
                        r"degrees?|beats per minute|bpm|kg|g|m|km|metres?|meters?)?", re.I)

# Two claims must be at least this similar before a difference counts as a
# contradiction rather than two unrelated statements.
_SAME_SUBJECT_MIN = 0.62


def _polarity(text: str) -> bool:
    """True when the statement is negated."""
    return bool(_NEGATION_RE.search(text))


def _antonym_conflict(a: str, b: str) -> str | None:
    """Conflict only when each side commits to a DIFFERENT term of the same pair.

    Disjointness is essential. A reference entry that mentions both "sorted" and
    "unsorted" (as a complete explanation naturally does) must not be treated as
    contradicting a claim that says "sorted" - that was a false positive that
    flagged correct statements.
    """
    ta, tb = set(normalize(a).split()), set(normalize(b).split())
    for group in _ANTONYM_GROUPS:
        hit_a = ta & group
        hit_b = tb & group
        if hit_a and hit_b and hit_a.isdisjoint(hit_b):
            return f"'{sorted(hit_a)[0]}' versus '{sorted(hit_b)[0]}'"
    return None


# "non-negative" vs "negative", "nonzero" vs "zero": one side explicitly negates the
# property the other asserts. This is a precise, explainable conflict signal.
_PREFIX_NEGATED_RE = re.compile(r"\bnon[- ]?([a-z]{3,15})\b", re.I)


def _prefix_negation_conflict(a: str, b: str) -> str | None:
    ta, tb = set(normalize(a).split()), set(normalize(b).split())
    neg_a = {m.group(1).lower() for m in _PREFIX_NEGATED_RE.finditer(a)}
    neg_b = {m.group(1).lower() for m in _PREFIX_NEGATED_RE.finditer(b)}

    # A asserts "non-X" while B asserts bare "X" (and never "non-X").
    for word in neg_a:
        if word in tb and word not in neg_b:
            return f"'non-{word}' versus '{word}'"
    for word in neg_b:
        if word in ta and word not in neg_a:
            return f"'{word}' versus 'non-{word}'"
    return None


def _complexity_conflict(a: str, b: str) -> str | None:
    ca = {m.group(1).lower().replace(" ", "") for m in _COMPLEXITY_RE.finditer(a)}
    cb = {m.group(1).lower().replace(" ", "") for m in _COMPLEXITY_RE.finditer(b)}
    if ca and cb and not (ca & cb):
        return f"complexity O({sorted(ca)[0]}) versus O({sorted(cb)[0]})"
    return None


def _numeric_conflict(a: str, b: str) -> str | None:
    na = {m.group(0).strip().lower() for m in _NUMBER_RE.finditer(a) if m.group(2)}
    nb = {m.group(0).strip().lower() for m in _NUMBER_RE.finditer(b) if m.group(2)}
    if na and nb and not (na & nb):
        # Only a conflict if the units match - "5 seconds" vs "3 kg" is not one.
        units_a = {m.group(2).lower() for m in _NUMBER_RE.finditer(a) if m.group(2)}
        units_b = {m.group(2).lower() for m in _NUMBER_RE.finditer(b) if m.group(2)}
        if units_a & units_b:
            return f"conflicting values {sorted(na)[0]} versus {sorted(nb)[0]}"
    return None


def _conflict_reason(a: str, b: str) -> str | None:
    """Why these two same-subject statements cannot both hold, or None."""
    if (reason := _complexity_conflict(a, b)) is not None:
        return reason
    if (reason := _antonym_conflict(a, b)) is not None:
        return reason
    if (reason := _prefix_negation_conflict(a, b)) is not None:
        return reason
    if (reason := _numeric_conflict(a, b)) is not None:
        return reason
    if _polarity(a) != _polarity(b):
        return "one statement asserts what the other denies"
    return None


def find_internal_contradictions(claims: list[Claim]) -> list[dict[str, Any]]:
    """Claim pairs within one response that cannot both be true."""
    if len(claims) < 2:
        return []

    texts = [c.text for c in claims]
    sim = embeddings.similarity_matrix(texts, texts)

    found: list[dict[str, Any]] = []
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            similarity = float(sim[i][j])
            if similarity < _SAME_SUBJECT_MIN:
                continue
            reason = _conflict_reason(texts[i], texts[j])
            if reason is None:
                continue
            found.append(
                {
                    "type": "internal",
                    "claim_a": texts[i],
                    "claim_b": texts[j],
                    "similarity": round(similarity, 4),
                    "reason": (
                        f"the response contradicts itself: {reason} "
                        f"(the two statements are {similarity:.2f} similar, so they are "
                        "about the same thing)"
                    ),
                    "span_a": [claims[i].start, claims[i].end],
                    "span_b": [claims[j].start, claims[j].end],
                }
            )
    return found


def find_external_contradictions(verifications) -> list[dict[str, Any]]:
    """Claims that conflict with the corpus entry that best matches them.

    A claim is only called contradicted when the corpus clearly addresses the same
    subject (high similarity) *and* asserts something incompatible. Otherwise it
    stays merely unsupported - we never upgrade missing evidence into a conflict.
    """
    found: list[dict[str, Any]] = []
    for v in verifications:
        if v.entry is None or v.similarity < _SAME_SUBJECT_MIN:
            continue
        reason = _conflict_reason(v.claim.text, v.entry.text)
        if reason is None:
            continue
        found.append(
            {
                "type": "external",
                "claim_a": v.claim.text,
                "claim_b": v.entry.text[:300],
                "similarity": round(v.similarity, 4),
                "reason": (
                    f"contradicts the reference corpus entry '{v.entry.title}' "
                    f"({v.entry.source}): {reason}"
                ),
                "span_a": [v.claim.start, v.claim.end],
                "source_id": v.entry.id,
                "source_title": v.entry.title,
            }
        )
    return found
