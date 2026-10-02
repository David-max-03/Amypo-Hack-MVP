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

# ---------------------------------------------------------------------------
# Generated questions: what is a claim and what is not
# ---------------------------------------------------------------------------
# A generated exam question is mostly not assertion. "Check if the number 37 is
# prime." is an instruction; "Each member has an email address." is a premise the
# problem sets up; "is_prime(2) should return True" is a specification; "This query
# groups the rows by email" describes the candidate's own solution. None of them can
# be true or false against a reference corpus, and holding them to source grounding
# marked nearly every generated question "unverifiable". These patterns are purely
# about sentence form - there is no topic vocabulary in them - and they are applied
# only when PS2 verifies a generated candidate, never to free text sent to /verify.

_LEAD_IN = (
    r"^\s*(?:(?:then|next|finally|first|second|third|also|now|additionally|however|instead|"
    r"please|lastly|afterwards?|task|question|problem|part\s+\w+|step\s+\w+|\(?[a-z0-9]{1,2}[.)])"
    r"\s*[:,.)-]?\s*)*"
)
# Verbs that open an imperative addressed to the learner.
_IMPERATIVE_VERBS = (
    "write|implement|create|design|develop|build|define|find|determine|check|calculate|"
    "compute|evaluate|solve|explain|describe|discuss|compare|contrast|identify|list|name|"
    "state|show|prove|derive|give|provide|return|use|consider|ensure|make sure|complete|"
    "fix|debug|correct|trace|predict|modify|rewrite|refactor|optimi[sz]e|test|validate|"
    "include|add|handle|print|output|sort|reverse|convert|classify|differentiate|simplify|"
    "express|justify|analy[sz]e|summari[sz]e|outline|illustrate|draw|select|choose|note|"
    "do not|don't|avoid|represent|arrange|count|remove|insert|delete|search|group|apply|"
    "demonstrate|construct|generate|produce|verify|label|match|order|rank|estimate|"
    "translate|draft|formulate|specify|locate|extend|adapt|rework|answer|decide|suggest|"
    "propose|recommend|refer|read|look|run|call|pass|assign|store|keep|leave|submit"
)
_IMPERATIVE_RE = re.compile(_LEAD_IN + rf"(?:{_IMPERATIVE_VERBS})\b(?!\s+of\b)", re.I)
# "You must ...", "Your function should ..." - addressed to the learner.
_SECOND_PERSON_RE = re.compile(_LEAD_IN + r"(?:you|your)\b", re.I)
# A requirement on the thing being built: a definite subject plus an obligation.
# "The function should return -1" is a requirement; "A recursive solution must use
# O(n) stack space" has a generic subject and stays a factual claim.
_REQUIREMENT_RE = re.compile(
    _LEAD_IN + r"(?:the|this|that|these|those|each|every|all|any|its|it|both)\b[^.?!]*?\b"
    r"(?:should|must|shall|needs? to|ha(?:s|ve) to|(?:is|are) (?:required|expected|supposed) to|"
    r"(?:is|are) not allowed|may not|cannot|can not|will be)\b",
    re.I,
)
# Examples, formats and givens.
_GIVEN_RE = re.compile(
    _LEAD_IN + r"(?:for example|example(?: usage)?|e\.g\.|for instance|input|output|"
    r"expected (?:output|result)|sample|test cases?|constraints?|note|hint|usage|given|"
    r"where)\b",
    re.I,
)
# A statement that would be true or false whatever this question is: a complexity, a
# definition, a general law, a comparison between concepts. These stay factual claims
# wherever they appear, including inside a question.
_GENERAL_CLAIM_RE = re.compile(
    r"\bO\(\s*[^)]{1,24}\)|\b(?:time|space) complexity\b"
    r"|\b(?:linear|constant|logarithmic|quadratic|exponential|polynomial)[- ](?:time|space)\b"
    r"|\b(?:worst|best|average)[- ]case\b"
    r"|\bis defined as\b|\brefers to\b|\b(?:is|are) (?:called|known as)\b"
    r"|\b(?:is|are) a (?:type|kind|form) of\b|\bby definition\b"
    r"|\b(?:in general|generally|typically|always|never|guarantee[sd]?)\b"
    r"|\b(?:faster|slower|cheaper|larger|smaller|better|worse|more \w+|less \w+) than\b",
    re.I,
)
# "A prime number is a natural number ...", "Binary search is an algorithm ...": a
# generic subject (no "the / this / each / your") defined with "is a".
_DEFINITION_RE = re.compile(
    r"^\s*(?!(?:the|this|that|these|those|each|every|all|your|you|it|its|their|our|we|i|"
    r"there|here|in|on|at|for|when|if|as|after|before|once|given)\b)"
    r"(?:an?\s+)?[A-Za-z][\w'/-]*(?:\s+[\w'/-]+){0,4}\s+(?:is|are)\s+(?:an?|the)\s",
    re.I,
)
# A sentence about the candidate's own solution: "This query groups ...", "The loop
# checks ...", "The HAVING clause filters ...".
_SOLUTION_NOUNS = (
    "function|method|query|subquery|code|solution|implementation|approach|program|script|"
    "snippet|class|loop|statement|expression|rule|selector|form|markup|routine|helper|"
    "variable|condition|clause|line|block|test cases?|example|answer|output|result|"
    "base case|recursive call|recursion|constructor|operation|step"
)
_SELF_REFERENCE_RE = re.compile(
    rf"^\s*(?:this|the|these|our|my)\s+(?:\S+\s+){{0,2}}?(?:{_SOLUTION_NOUNS})\b"
    r"|^\s*this\s+(?:algorithm|technique|version|variant)\b"
    r"|^\s*(?:here|in (?:this|the) (?:solution|code|implementation|approach|query|example|"
    r"function|answer))\b",
    re.I,
)
# In the explanation that follows reference code, "It iterates ..." / "We keep ..."
# are still about that code.
_PRONOUN_LED_RE = re.compile(r"^\s*(?:it|we|they)\b", re.I)


# Values and names a problem introduces: numbers, and identifiers that carry a digit
# ("P3", "x2"). A sentence of the answer that uses one of them is working this
# particular problem - "P3 runs from time 6 to time 10" - not stating a general fact.
_INSTANCE_TOKEN_RE = re.compile(r"(?<![\w.])[A-Za-z]{0,6}\d+(?:\.\d+)?(?![\w])")


def instance_tokens(text: str) -> frozenset[str]:
    return frozenset(m.group(0).lower() for m in _INSTANCE_TOKEN_RE.finditer(text or ""))


def _is_general_claim(sentence: str) -> bool:
    return bool(_GENERAL_CLAIM_RE.search(sentence) or _DEFINITION_RE.match(sentence))


def classify_question_sentence(sentence: str) -> str:
    """Label one sentence of a generated question's text.

    A question's declarative sentences are its givens. They are checked as facts
    only when they state something general - a complexity, a definition, a law -
    because that is the only kind of statement in a question that can be wrong
    about the world rather than merely part of the problem.
    """
    if _CITATION_RE.search(sentence):
        return "citation"
    if _OPINION_RE.search(sentence):
        return "opinion"
    if sentence.rstrip().endswith("?"):
        return "instruction"
    if _SCENARIO_FRAME_RE.search(sentence) or _ASSUMPTION_RE.search(sentence):
        return "assumption"
    if _IMPERATIVE_RE.match(sentence) or _SECOND_PERSON_RE.match(sentence) \
            or _REQUIREMENT_RE.match(sentence):
        return "instruction"
    if _GIVEN_RE.match(sentence):
        return "setup"
    if _is_general_claim(sentence):
        return "factual"
    return "setup"


def classify_answer_sentence(
    sentence: str, *, code_answer: bool, problem_tokens: frozenset[str] = frozenset()
) -> str:
    """Label one prose sentence of a generated answer key.

    The answer's assertions are what must be right, so the default stays "factual".
    Only sentences about the candidate's own solution, or working this problem's own
    values, are set aside - and a general statement ("this runs in O(1) space") is
    never set aside.
    """
    if _CITATION_RE.search(sentence):
        return "citation"
    if _OPINION_RE.search(sentence):
        return "opinion"
    if _is_general_claim(sentence):
        return "answer" if _ANSWER_RE.search(sentence) else "factual"
    if _GIVEN_RE.match(sentence):
        return "setup"
    if _SELF_REFERENCE_RE.match(sentence) or (code_answer and _PRONOUN_LED_RE.match(sentence)):
        return "explanation"
    if problem_tokens and instance_tokens(sentence) & problem_tokens:
        return "explanation"
    label = classify_claim(sentence)
    # `classify_claim` files a sentence under "inference" when its verb is not on a
    # short list, which leaves "HAVING filters rows before grouping." unchecked. In an
    # answer key a complete declarative sentence is an assertion unless it is marked
    # as a conclusion, so it is checked.
    if (
        label == "inference"
        and not _INFERENCE_RE.search(sentence)
        and sentence.rstrip().endswith(".")
        and len(content_tokens(sentence)) >= 4
        and not re.search(r"[`(){}\[\]=<>]", sentence)
    ):
        return "factual"
    return label


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
# Code that is not a statement in a programming language: a line of markup, and a
# line of a SQL statement. SQL keywords are matched in upper case only (or as a full
# `select ... from` on one line) so that prose such as "Select the best answer" or
# "Where a claim is unsupported ..." is never mistaken for a query.
_MARKUP_LINE_RE = re.compile(r"^\s*</?[A-Za-z][\w-]*(?:\s[^<>]*)?/?>")
# A line of a query does not end in a full stop; "HAVING filters groups after GROUP
# BY." is a sentence about SQL, not SQL.
_SQL_LINE_RE = re.compile(
    r"^\s*(?:SELECT|FROM|WHERE|GROUP BY|HAVING|ORDER BY|INSERT INTO|UPDATE|DELETE FROM|"
    r"CREATE (?:TABLE|INDEX|VIEW)|(?:LEFT|RIGHT|INNER|OUTER|FULL|CROSS) JOIN|JOIN|ON|LIMIT|"
    r"OFFSET|UNION|WITH|VALUES|SET|AND|OR)\b(?!.*\.\s*$)"
)
_SQL_INLINE_RE = re.compile(
    r"^\s*select\b.+\bfrom\s+\w+\s*(?:;|$|where\b|group\b|order\b|join\b|limit\b|having\b)"
)


def _is_code_line(line: str) -> bool:
    return bool(
        _CODE_KEYWORD_RE.match(line)
        or _BLOCK_HEADER_RE.match(line)
        or _ASSIGNMENT_RE.match(line)
        or _BRACE_OR_STATEMENT_RE.search(line)
        or _CODE_COMMENT_RE.match(line)
        or _MARKUP_LINE_RE.match(line)
        or _SQL_LINE_RE.match(line)
        or _SQL_INLINE_RE.match(line)
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


def extract_claims(
    text: str, *, question_end: int | None = None, code_answer: bool = False
) -> list[Claim]:
    """Split a response into labelled, span-located claims.

    Each claim keeps its character offsets in the original text so the UI can
    highlight the exact words that triggered a flag.

    `question_end` marks a generated candidate: characters before it are the question,
    the rest is the answer key, and each part is classified by its own rules. Without
    it (free text sent to /verify) every sentence is classified as before.
    """
    if not text or not text.strip():
        return []

    problem_tokens = instance_tokens(text[:question_end]) if question_end is not None else frozenset()
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
                claim_type=(  # type: ignore[arg-type]
                    classify_claim(sentence) if question_end is None
                    else classify_question_sentence(sentence) if start < question_end
                    else classify_answer_sentence(
                        sentence, code_answer=code_answer, problem_tokens=problem_tokens
                    )
                ),
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
