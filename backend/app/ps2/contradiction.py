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
from ..core.text_utils import content_tokens, normalize, split_sentences
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

# Words that deny the main statement. "without" is deliberately absent: it adds a
# constraint ("reverse it in place without extra structures") rather than negating
# the claim, and counting it flagged correct questions as contradicting the corpus.
_NEGATION_RE = re.compile(
    r"\b(not|never|no|cannot|can't|doesn't|does not|isn't|is not|won't|will not|"
    r"aren't|are not)\b",
    re.I,
)

# Big-O complexity claims - the single most common place a generated answer is wrong.
_COMPLEXITY_RE = re.compile(r"o\(\s*([^)]{1,20}?)\s*\)", re.I)

_NUMBER_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(%|percent|seconds?|ms|minutes?|hours?|"
                        r"degrees?|beats per minute|bpm|kg|g|m|km|metres?|meters?)?", re.I)

# Two claims must be at least this similar before a difference counts as a
# contradiction rather than two unrelated statements.
_SAME_SUBJECT_MIN = 0.62

# A bare negation difference is the weakest contradiction signal. On its own,
# "reverse it in place *without* extra structures" vs "return the new head" (same
# topic, 0.68 similar) was flagged as the response contradicting itself - 6 of 10
# correct generated questions came out "misleading". A genuine polarity flip says
# the *same thing* once negated, so the two statements must also share most of their
# content words after the negation words are removed.
_POLARITY_MIN_SHARED = 0.6


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


# ---------------------------------------------------------------------------
# Complexity claims
# ---------------------------------------------------------------------------
# "O(log n) time with O(1) extra space" vs "O(n) time with O(1) extra space" share
# O(1), so a check that only fired on fully disjoint Big-O sets marked the wrong
# claim as supported. Each Big-O term is now tied to the dimension it describes
# (time or space) and compared per dimension, clause by clause.
_TIME_WORDS = re.compile(r"\b(time|runtime|running|runs?|steps|operations|comparisons)\b", re.I)
_SPACE_WORDS = re.compile(r"\b(space|memory|auxiliary|storage|stack\s+frames?)\b", re.I)
# Two statements about different algorithms are not the same claim, even if they
# otherwise read alike ("recursive reversal uses O(n) space" vs "iterative reversal
# uses O(1) extra space").
_APPROACH_GROUPS = [
    ("recursive", re.compile(r"\brecurs(ive|ively|ion)\b", re.I)),
    ("iterative", re.compile(r"\biterat(ive|ively|ion)\b", re.I)),
]
# Content words that describe complexity itself, not the subject of the claim.
_COMPLEXITY_VOCAB = {
    "time", "runtime", "running", "runs", "run", "steps", "operations", "space", "memory",
    "extra", "auxiliary", "additional", "constant", "linear", "logarithmic", "quadratic",
    "uses", "use", "requires", "takes", "complexity", "log", "stack", "frame", "frames",
}
# Clauses must share at least a third of their subject words to be "about the same
# thing". It only has to separate clauses of a multi-part corpus entry that describe a
# different approach (1 of 6 shared); 0.5 dropped real contradictions stated wordily.
_COMPLEXITY_SAME_SUBJECT = 0.34


def _norm_complexity(expr: str) -> str:
    e = expr.lower().replace("\u00b2", "^2").replace("\u00b3", "^3")
    return re.sub(r"[\s*]", "", e)


def _dimensioned_complexities(clause: str) -> dict[str, set[str]]:
    """{"time": {...}, "space": {...}, "unlabelled": {...}} for one clause."""
    found: dict[str, set[str]] = {"time": set(), "space": set(), "unlabelled": set()}
    for m in _COMPLEXITY_RE.finditer(clause):
        term = _norm_complexity(m.group(1))
        after = clause[m.end() : m.end() + 24]
        before = clause[max(0, m.start() - 28) : m.start()]
        # The word right after a term ("O(n) time") is the strongest signal; the words
        # before it ("uses O(n)", "space complexity of O(n)") come next.
        if _SPACE_WORDS.search(after):
            found["space"].add(term)
        elif _TIME_WORDS.search(after):
            found["time"].add(term)
        elif _SPACE_WORDS.search(before):
            found["space"].add(term)
        elif _TIME_WORDS.search(before):
            found["time"].add(term)
        else:
            found["unlabelled"].add(term)
    return found


def _approaches(text: str) -> set[str]:
    return {name for name, rx in _APPROACH_GROUPS if rx.search(text)}


def _different_approaches(a: str, b: str) -> bool:
    pa, pb = _approaches(a), _approaches(b)
    return bool(pa and pb and not (pa & pb))


def _same_complexity_subject(a: str, b: str) -> bool:
    strip = lambda t: {w for w in content_tokens(_COMPLEXITY_RE.sub(" ", t)) if w not in _COMPLEXITY_VOCAB}
    ta, tb = strip(a), strip(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= _COMPLEXITY_SAME_SUBJECT


def _complexity_conflict(a: str, b: str) -> str | None:
    # 1. Per-dimension comparison, clause by clause.
    for sa in _clauses(a):
        da = _dimensioned_complexities(sa)
        if not any(da.values()):
            continue
        for sb in _clauses(b):
            db = _dimensioned_complexities(sb)
            if not any(db.values()) or _different_approaches(sa, sb):
                continue
            if not _same_complexity_subject(sa, sb):
                continue
            for dim in ("time", "space"):
                if da[dim] and db[dim] and not (da[dim] & db[dim]):
                    return (
                        f"{dim} complexity O({sorted(da[dim])[0]}) versus "
                        f"O({sorted(db[dim])[0]})"
                    )

    # 2. Fallback for terms with no time/space label ("binary search is O(log n)"):
    #    same subject, same approach, no Big-O term in common. Labelled terms are
    #    only ever compared per dimension above - "O(n) time" and "O(1) space"
    #    describe different things and are not a conflict.
    if _different_approaches(a, b) or not _same_complexity_subject(a, b):
        return None
    da, db = _dimensioned_complexities(a), _dimensioned_complexities(b)
    ua, ub = da["unlabelled"], db["unlabelled"]
    if not (ua or ub):
        return None
    ca = ua | da["time"] | da["space"]
    cb = ub | db["time"] | db["space"]
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
    if _opposite_polarity_statement(a, b):
        return "one statement asserts what the other denies"
    return None


def _opposite_polarity_statement(a: str, b: str) -> bool:
    """Is some clause of `a` the negation of some clause of `b`?

    Compared clause by clause: a corpus entry is often several sentences, and a
    "not" in its second sentence (about a different approach) says nothing about a
    claim that matches its first.
    """
    for sa in _clauses(a):
        for sb in _clauses(b):
            if _polarity(sa) != _polarity(sb) and _same_statement_modulo_negation(sa, sb):
                return True
    return False


def _clauses(text: str) -> list[str]:
    """Sentences, further split at semicolons - each side of ';' is its own assertion
    ("X is in-place; creating a new list is not")."""
    parts = [c.strip() for s in (split_sentences(text) or [text]) for c in s.split(";")]
    return [c for c in parts if c] or [text]


def _same_statement_modulo_negation(a: str, b: str) -> bool:
    """Do `a` and `b` share most content words once negation words are removed?"""
    ta = set(content_tokens(_NEGATION_RE.sub(" ", a)))
    tb = set(content_tokens(_NEGATION_RE.sub(" ", b)))
    if not ta or not tb:
        return False
    # Overlap relative to the shorter statement, so "X is Y" vs "X is not Y, as
    # shown" still counts as the same statement.
    return len(ta & tb) / min(len(ta), len(tb)) >= _POLARITY_MIN_SHARED


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
