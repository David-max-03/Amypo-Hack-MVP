"""AI Response Analyzer (PS2).

Segments a response into individually checkable units and labels what kind of
statement each one is. PS2 explicitly requires distinguishing factual information
from assumptions, opinions and generated inferences, because only factual and
answer claims should be held to the source-grounding standard - penalising an
opinion for being "unsupported" is exactly the false positive the rubric punishes.
"""

from __future__ import annotations

import re

from ..core.text_utils import content_tokens, find_span, split_sentences
from ..schemas import Claim

# A citation-like reference: "according to X", "[3]", "(Smith, 2019)", "RFC 2616".
_CITATION_RE = re.compile(
    r"(according to\s+[A-Z][\w .&'-]{2,40}"
    r"|as (?:stated|reported|shown|documented) (?:in|by)\s+[A-Z][\w .&'-]{2,40}"
    r"|\[\d{1,3}\]"
    r"|\((?:[A-Z][\w'-]+(?:\s+(?:et al\.?|and\s+[A-Z][\w'-]+))?,\s*\d{4})\)"
    r"|\b(?:RFC|ISO|IEEE|ANSI|NIST)[\s-]?\d{2,5}\b"
    r"|\bper\s+(?:the\s+)?[A-Z][\w .&'-]{2,40}\s+(?:standard|specification|guideline)s?\b)",
    re.I,
)

# Deliberately narrow: only an explicit subjective frame makes a sentence an opinion.
# Weaker markers such as "preferred" or "better than" routinely appear inside
# genuinely factual statements, and treating those as opinions would exempt real
# factual errors from verification - the false NEGATIVE that matters most here.
_OPINION_RE = re.compile(
    r"\b(i think|i believe|i feel|in my (?:opinion|view)|to my mind|arguably|"
    r"it seems to me|personally|in our view|we believe|"
    r"the (?:best|nicest|cleanest) (?:way|approach|option|choice) is|"
    r"is (?:more )?elegant|is beautiful|is ugly)\b",
    re.I,
)

_ASSUMPTION_RE = re.compile(
    r"\b(assum(?:e|ing|ption)|suppose|let us say|let's say|given that|if we take|"
    r"for the sake of|presum(?:e|ably)|hypothetically)\b",
    re.I,
)

# Scenario framing in a generated question ("You are developing a version control
# system...") sets up a hypothetical; it asserts nothing about the world, so holding
# it to corpus grounding only manufactures "unsupported claim" flags. Anchored at
# the start of the sentence and limited to task-framing verbs, so "You are right
# that X" is still read as a claim.
_SCENARIO_FRAME_RE = re.compile(
    r"^\s*(?:you(?: are|'re)\s+(?:a|an|the|working|developing|building|tasked|given|"
    r"managing|designing|writing|creating|implementing|helping|organi[sz]ing|"
    r"responsible|part of|asked|hired|in charge)\b"
    r"|you (?:work|have been (?:asked|hired|tasked))\b"
    r"|your (?:task|goal|job|assignment|challenge) is\b"
    r"|imagine\b|picture this\b|as part of\b|in this (?:scenario|system|problem|task)\b)",
    re.I,
)

_INFERENCE_RE = re.compile(
    r"\b(therefore|thus|hence|so it follows|consequently|as a result|which means|"
    r"this implies|we can conclude|it follows that)\b",
    re.I,
)

_ANSWER_RE = re.compile(
    r"\b(the answer is|answer:|the (?:correct )?(?:result|output|solution) is|"
    r"equals?\b|the value is|final answer|therefore the answer)\b",
    re.I,
)

# A statement asserting a checkable fact: has a definite verb and concrete content.
_FACTUAL_HINT_RE = re.compile(
    r"\b(is|are|was|were|has|have|had|runs?|takes?|requires?|costs?|equals?|contains?|"
    r"consists?|means?|defined|produces?|causes?|results?|measures?|uses?|needs?|"
    r"must|shall|should|will|can|supports?|returns?|performs?|operates?|works?|"
    r"occurs?|happens?|provides?|allows?|prevents?|reduces?|increases?|decreases?|"
    r"submits?|files?|holds?|stores?|maps?|converts?)\b",
    re.I,
)

# Minimum content words for a fragment to be worth verifying on its own. Set to 2
# rather than 3 because short assertions ("A stack is LIFO") are perfectly checkable
# factual claims, and dropping them would let real errors through unverified. Genuine
# fragments ("Yes.", "OK.") carry only one content word and are still excluded.
_MIN_CLAIM_TOKENS = 2

# ---------------------------------------------------------------------------
# Code masking
# ---------------------------------------------------------------------------
# Generated answer keys are code. Read as prose, `if not head or not head.next:`
# looks like a negated claim and trips the self-contradiction rule, and every
# `x = y` line becomes an "unsupported factual claim". Code is not a claim about
# the world, so it is blanked out before claim extraction - with spaces, so every
# offset still points at the same characters of the original text.

_CODE_KEYWORD_RE = re.compile(
    r"^\s*(?:def|class|return|yield|import|from\s+\S+\s+import|elif|else\s*:|try\s*:|"
    r"except\b|finally\s*:|with\s+.+:|lambda\b|assert\b|print\s*\(|raise\b|pass\b|"
    r"break\b|continue\b|public|private|protected|static|function\b|const\b|let\b|var\b|"
    r"fn\b|func\b|#include|using\s+namespace|console\.log|System\.out)"
)
# A Python block header: `if ...:`, `for x in y:`, `while cond:`.
_BLOCK_HEADER_RE = re.compile(r"^\s*(?:if|for|while)\b.*:\s*(?:#.*)?$")
# `name = value`, `a.b[i] += 1`, `x, y = y, x` - assignment, not `==` comparison.
_ASSIGNMENT_RE = re.compile(r"^\s*[\w.\[\]]+(?:\s*,\s*[\w.\[\]]+)*\s*(?:[-+*/%]?=)(?!=)\s*\S")
# Lines that are pure structure (braces) or end like a statement in C-family code.
_BRACE_OR_STATEMENT_RE = re.compile(r"^\s*[{}()\[\];]+\s*$|;\s*$|\{\s*$")
# A line that starts with `#` or `//` is a comment (or a Markdown heading) - never a
# factual claim. Numbered test-case comments ("# 1. Reversing a list with no
# duplicates" / "# 2. ... with duplicates") were read as contradicting claims.
_CODE_COMMENT_RE = re.compile(r"^\s*(?:#|//)")
_FENCE_RE = re.compile(r"^\s*```")


def _is_code_line(line: str) -> bool:
    return bool(
        _CODE_KEYWORD_RE.match(line)
        or _BLOCK_HEADER_RE.match(line)
        or _ASSIGNMENT_RE.match(line)
        or _BRACE_OR_STATEMENT_RE.search(line)
        or _CODE_COMMENT_RE.match(line)
    )


def mask_code(text: str) -> str:
    """Return `text` with code lines replaced by spaces (same length, same offsets).

    Masks fenced blocks, lines that are recognisably code, and the indented body
    that follows a code line (so a wrapped expression inside a function is not
    read as prose). Prose - including prose that mentions `inline_code()` - is kept.
    """
    if not text:
        return text
    out: list[str] = []
    in_fence = False
    in_block = False  # inside the indented body of a code construct
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body):]
        stripped = body.strip()
        indented = bool(body) and body[0] in " \t"

        if _FENCE_RE.match(body):
            in_fence = not in_fence
            is_code = True
        elif in_fence:
            is_code = True
        elif not stripped:
            is_code = False
        elif _is_code_line(body):
            is_code = True
        else:
            is_code = in_block and indented

        if stripped:
            in_block = is_code
        out.append((" " * len(body) if is_code else body) + ending)
    return "".join(out)


def classify_claim(sentence: str) -> str:
    """Label a sentence by the kind of statement it makes.

    Order matters: an explicit opinion or assumption marker overrides the factual
    reading, since "I think X is O(1)" is a stance, not an assertable fact.
    """
    if _CITATION_RE.search(sentence):
        return "citation"
    if _OPINION_RE.search(sentence):
        return "opinion"
    if _ASSUMPTION_RE.search(sentence) or _SCENARIO_FRAME_RE.search(sentence):
        return "assumption"
    if _ANSWER_RE.search(sentence):
        return "answer"
    if _INFERENCE_RE.search(sentence):
        return "inference"
    if _FACTUAL_HINT_RE.search(sentence):
        return "factual"
    return "inference"


def extract_claims(text: str) -> list[Claim]:
    """Split a response into labelled, span-located claims.

    Each claim keeps its character offsets in the original text so the UI can
    highlight the exact words that triggered a flag.
    """
    if not text or not text.strip():
        return []

    claims: list[Claim] = []
    cursor = 0
    for sentence in split_sentences(text):
        if len(content_tokens(sentence)) < _MIN_CLAIM_TOKENS:
            continue

        # Search from `cursor` so repeated sentences map to distinct spans.
        span = find_span(text[cursor:], sentence)
        if span is None:
            span = find_span(text, sentence)
            start, end = span if span else (0, len(sentence))
        else:
            start, end = span[0] + cursor, span[1] + cursor
            cursor = end

        claims.append(
            Claim(
                text=sentence,
                claim_type=classify_claim(sentence),  # type: ignore[arg-type]
                start=start,
                end=end,
            )
        )

    return claims


def verifiable_claims(claims: list[Claim]) -> list[Claim]:
    """Claims that must be grounded against the corpus.

    Opinions and explicit assumptions are excluded by design: flagging them as
    unsupported would inflate the false-positive rate PS2 scores at 15%.
    """
    return [c for c in claims if c.claim_type in {"factual", "answer", "citation"}]


def extract_citations(text: str) -> list[str]:
    """Citation-like references found in the text, for the citation checker."""
    return [m.group(0).strip() for m in _CITATION_RE.finditer(text or "")]
