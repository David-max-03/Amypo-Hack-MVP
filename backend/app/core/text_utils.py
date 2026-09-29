"""Shared lexical helpers used by both PS8 structural validation and PS2 verification.

These are intentionally dependency-free and deterministic so that unit tests can
assert exact behaviour without loading any model.
"""

from __future__ import annotations

import re

# Words that carry no topical signal. Kept deliberately small: an over-aggressive
# stop list destroys the concept-overlap signal PS8 depends on.
STOPWORDS: frozenset[str] = frozenset(
    """
    a an the and or but if then else of to in on at by for with from into over under
    is are was were be been being am do does did doing have has had having
    this that these those it its as not no so than too very can will just
    you your we our they their he she his her i me my
    write given implement create design return returns using use used
    please function method program code question answer
    """.split()
)

_TOKEN_RE = re.compile(r"[a-z0-9_+#]+")
# Sentence splitter that does not break on decimals ("0.75") or "e.g.".
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")


def normalize(text: str) -> str:
    """Lowercase and collapse whitespace."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def tokenize(text: str) -> list[str]:
    """Lowercased alphanumeric tokens, preserving identifiers like `big_o` and `c++`."""
    return _TOKEN_RE.findall(normalize(text))


def content_tokens(text: str) -> list[str]:
    """Tokens with stopwords and 1-character noise removed."""
    return [t for t in tokenize(text) if t not in STOPWORDS and len(t) > 1]


def token_set(text: str) -> set[str]:
    return set(content_tokens(text))


def jaccard(a: str, b: str) -> float:
    """Lexical similarity in [0,1] over content-token sets."""
    sa, sb = token_set(a), token_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def overlap_coefficient(a: str, b: str) -> float:
    """Fraction of the *smaller* token set that is shared.

    Preferred over Jaccard for concept preservation: a long candidate should not be
    penalised merely for adding scenario detail around the same core concept.
    """
    sa, sb = token_set(a), token_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def keyword_grounding(claim: str, evidence: str) -> float:
    """Fraction of the claim's content words that literally appear in the evidence.

    PS2 requires that semantic similarity alone is never treated as proof, so this
    lexical check is combined with the embedding score in the source verifier.
    """
    ct = token_set(claim)
    if not ct:
        return 0.0
    et = token_set(evidence)
    return len(ct & et) / len(ct)


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences, also treating list items and newlines as breaks."""
    if not text:
        return []
    # Bullet/numbered list items are independent claims.
    prepared = re.sub(r"\n\s*(?:[-*•]|\d+[.)])\s+", "\n", text)
    parts: list[str] = []
    for line in prepared.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts.extend(p.strip() for p in _SENTENCE_RE.split(line) if p.strip())
    return parts


def find_span(haystack: str, needle: str) -> tuple[int, int] | None:
    """Character offsets of `needle` inside `haystack`, or None.

    Falls back to a whitespace-insensitive search so that a claim recovered from a
    re-joined sentence still resolves to a real span in the original text — this is
    what lets the UI highlight the exact offending words.
    """
    if not needle or not haystack:
        return None
    idx = haystack.find(needle)
    if idx >= 0:
        return (idx, idx + len(needle))

    pattern = r"\s+".join(re.escape(w) for w in needle.split())
    m = re.search(pattern, haystack)
    if m:
        return (m.start(), m.end())
    return None
