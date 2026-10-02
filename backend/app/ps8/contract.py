"""Seed Contract (PS8).

A seed question fixes an educational intent; a variation may change one requested
dimension and nothing else. The contract writes that down once per seed, in a form
both the generation prompt and the structural validator use:

  * what must stay the same - the core concept, the learning objective, the task,
    the concept-bearing terms, any technology the seed names, the structure it
    operates on, and its stated constraints;
  * what may change - the dimensions of the strategies eligible for this seed.

Everything here is derived from the seed text and the existing seed analysis by
local, deterministic computation. There are no topic lists: which words carry the
concept is measured (leave-one-out on the seed's embedding), not looked up.
Fields that cannot be determined reliably are left empty rather than guessed.
"""

from __future__ import annotations

import re
from functools import lru_cache

import numpy as np

from ..core.embeddings import embeddings
from ..core.text_utils import content_tokens, light_stem, tokenize
from ..schemas import SeedContract, SeedMetadata

# Salient terms are taken, in order of salience, until they explain this share of
# the seed's meaning (at most _MAX_CORE of them).
_CORE_MASS = 0.60
_MAX_CORE = 3
# A term absent from the candidate still counts as present when a NEW candidate word
# is at least this similar to it ("differentiate" for "derivative").
SOFT_MATCH_MIN = 0.60

# Words of instruction rather than content. They are never concept-bearing.
_INSTRUCTION_WORDS = frozenset(
    "explain describe discuss compare contrast define identify find calculate compute "
    "determine check whether how what why which when where between difference "
    "following briefly prove derive solve evaluate decide decides each every all any".split()
)

stem = light_stem


def split_identifiers(text: str) -> str:
    """`getMin` -> `get Min`, `is_prime` -> `is prime`, so names in code count as words."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text or "")
    return text.replace("_", " ")


def candidate_terms(text: str) -> list[str]:
    """Unique content tokens of a candidate, with identifiers split into words."""
    return list(dict.fromkeys(content_tokens(split_identifiers(text))))


# ----------------------------------------------------------------------
# What the seed states explicitly
# ----------------------------------------------------------------------
# Technologies, protocols and proper names are written as acronyms (SQL, TCP, HTML),
# with symbols (C++, C#), or capitalised in the middle of a sentence (Python).
_ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,}(?:[+#]+)?\b|\b[A-Z][+#]+")
_PROPER_RE = re.compile(r"(?<=[a-z,;:)] )([A-Z][a-z]+(?:[A-Z][a-z]+)*)\b")

_CONSTRAINT_RE = re.compile(
    r"\bwithout (?:using )?[^.,;?]+"
    r"|\busing only [^.,;?]+"
    r"|\bin[- ]place\b"
    r"|\bin a single pass\b"
    r"|\bO\([^)]*\)(?: (?:time|space|extra space|auxiliary space))?"
    r"|\b(?:at most|at least|no more than|fewer than|exactly) [^.,;?]+"
    r"|\b(?:must|may|should|can) not [^.,;?]+|\b(?:cannot|can't|must) [^.,;?]+"
    r"|\b(?:is|are) not allowed[^.,;?]*|\bnot allowed to [^.,;?]+"
    r"|\b(?:time|space) complexity[^.,;?]*"
    r"|\b(?:limited|restricted) to [^.,;?]+",
    re.I,
)
_NUMBER_RE = re.compile(r"(?<![A-Za-z_])\d+(?:\.\d+)?")


def named_elements(text: str) -> list[str]:
    """Technologies / proper names the text states, in order of appearance."""
    found: list[tuple[int, str]] = [(m.start(), m.group(0)) for m in _ACRONYM_RE.finditer(text or "")]
    found += [(m.start(1), m.group(1)) for m in _PROPER_RE.finditer(text or "")]
    out: list[str] = []
    for _, name in sorted(found):
        if name.lower() not in {n.lower() for n in out}:
            out.append(name)
    return out


def constraint_clauses(text: str) -> list[str]:
    """Explicit constraint clauses in the text ("without using a loop", "in O(n) time")."""
    out: list[str] = []
    for m in _CONSTRAINT_RE.finditer(text or ""):
        clause = re.sub(r"\s+", " ", m.group(0)).strip().lower()
        if clause and clause not in out:
            out.append(clause)
    return out


def parameters(text: str) -> list[str]:
    """Concrete numeric values in the text - what a parameter variation changes."""
    return list(dict.fromkeys(_NUMBER_RE.findall(text or "")))


# ----------------------------------------------------------------------
# Which words carry the concept
# ----------------------------------------------------------------------
def term_salience(seed_text: str) -> list[tuple[str, float]]:
    """Each content term's share of the seed's meaning, most salient first.

    Measured by leave-one-out: how far the seed's embedding moves when the term is
    removed. "prime" dominates "Write a function to check whether a number is
    prime"; "number" and "check" barely register. Tokens carrying digits are
    parameters, and instruction words are never concepts, so both are skipped.
    """
    words = (seed_text or "").split()
    terms = [
        t for t in dict.fromkeys(content_tokens(seed_text))
        if t not in _INSTRUCTION_WORDS and not any(ch.isdigit() for ch in t)
    ]
    if not terms:
        return []
    ablated = [
        " ".join(w for w in words if term not in tokenize(w)) or seed_text for term in terms
    ]
    vectors = embeddings.encode([seed_text, *ablated])
    full = vectors[0]
    shifts: list[float] = []
    for vec in vectors[1:]:
        denom = float(np.linalg.norm(full) * np.linalg.norm(vec)) or 1.0
        shifts.append(max(0.0, 1.0 - float(np.dot(full, vec)) / denom))
    total = sum(shifts) or 1.0
    ranked = sorted(zip(terms, shifts), key=lambda pair: -pair[1])
    return [(term, round(shift / total, 4)) for term, shift in ranked]


def core_phrase(seed_text: str) -> str:
    """The seed's most concept-bearing terms, in the order the seed uses them."""
    core = _core_terms(term_salience(seed_text))
    order = {t: i for i, t in enumerate(dict.fromkeys(content_tokens(seed_text)))}
    return " ".join(sorted(core, key=lambda t: order.get(t, 0)))


def _core_terms(salience: list[tuple[str, float]]) -> list[str]:
    core: list[str] = []
    mass = 0.0
    for term, share in salience:
        if len(core) >= _MAX_CORE or (core and mass >= _CORE_MASS):
            break
        core.append(term)
        mass += share
    return core


def _required_elements(seed: SeedMetadata, salience: list[tuple[str, float]]) -> list[str]:
    """The terms a variation must still be about.

    The most salient term is always required. One further salient term is required
    when the seed analysis (topic / core concept) names it too - that is what
    separates "binary" in "binary search" (part of the concept) from "email" in
    "duplicate email addresses" (the data a scenario variation may replace). Two
    terms is the limit: demanding more rejects faithful variations that simply do
    not repeat every word of the seed.
    """
    core = _core_terms(salience)
    if not core:
        return []
    analysed = {stem(t) for t in content_tokens(f"{seed.core_concept} {seed.topic}")}
    required = [core[0]] + [t for t in core[1:] if stem(t) in analysed][:1]
    order = {t: i for i, t in enumerate(dict.fromkeys(content_tokens(seed.raw_seed)))}
    return sorted(dict.fromkeys(required), key=lambda t: order.get(t, 0))


@lru_cache(maxsize=256)
def _build(raw_seed: str, domain: str, topic: str, core_concept: str, question_type: str,
           learning_objective: str) -> SeedContract:
    from . import strategies, variation_planner  # local: avoids an import cycle
    from .validation.validators import seed_data_structure

    seed = SeedMetadata(
        domain=domain, topic=topic, core_concept=core_concept, question_type=question_type,
        difficulty="medium", difficulty_score=0.55, learning_objective=learning_objective,
        raw_seed=raw_seed,
    )
    salience = term_salience(raw_seed)
    required = _required_elements(seed, salience)
    named = named_elements(raw_seed)
    # A data structure is immutable only when it carries the seed's concept. In
    # "reverse a linked list" it does; in "binary search on a sorted array" the array
    # is incidental, and a variation on a sorted list is still binary search.
    anchor = seed_data_structure(seed)
    core_stems = {stem(t) for t in _core_terms(salience)} | {stem(t) for t in required}
    if anchor and not any(stem(t) in core_stems for t in tokenize(anchor)):
        anchor = None
    constraints = constraint_clauses(raw_seed)

    immutable = [
        f"the core learning objective: {learning_objective}",
        f"the task the learner performs, as the seed states it ({question_type})",
        f"the domain: {domain}",
    ]
    if required:
        immutable.append("the subject: " + ", ".join(required))
    if named:
        immutable.append("the technology or named concept: " + ", ".join(named))
    if anchor:
        immutable.append(f"the structure it operates on: {anchor}")

    return SeedContract(
        domain=domain,
        core_concept=core_concept,
        learning_objective=learning_objective,
        task_type=question_type,
        task=raw_seed,
        required_elements=required,
        element_weights={term: share for term, share in salience},
        named_elements=named,
        structure_anchor=anchor,
        constraints=constraints,
        parameters=parameters(raw_seed),
        immutable_elements=immutable,
        allowed_variation_dimensions=[
            s.dimension for s in variation_planner.eligible_strategies_for_type(question_type)
        ] or [s.dimension for s in strategies.list_strategies()],
    )


def build_contract(seed: SeedMetadata) -> SeedContract:
    """The contract for a seed. Cached: the same seed analysis gives the same contract."""
    return _build(seed.raw_seed, seed.domain, seed.topic, seed.core_concept,
                  seed.question_type, seed.learning_objective)


def get_contract(seed: SeedMetadata) -> SeedContract:
    return seed.contract or build_contract(seed)


# ----------------------------------------------------------------------
# Is a required element still present in a candidate?
# ----------------------------------------------------------------------
def _lexically_present(term: str, cand_terms: list[str], cand_stems: set[str]) -> bool:
    ts = stem(term)
    if ts in cand_stems:
        return True
    for c in cand_terms:
        cs = stem(c)
        # "min" for "minimum" (an abbreviation), "primality" for "prime".
        if len(cs) >= 3 and term.startswith(cs) and len(cs) < len(term):
            return True
        if len(ts) >= 4 and cs.startswith(ts):
            return True
    return False


def _acronym_covered(seed_text: str, cand_text: str) -> set[str]:
    """Seed terms the candidate refers to by acronym: "KNN" covers k, nearest, neighbours."""
    words = [w for w in tokenize(seed_text.replace("-", " "))]
    covered: set[str] = set()
    for acronym in {m.group(0).lower() for m in re.finditer(r"\b[A-Z]{2,6}\b", cand_text or "")}:
        n = len(acronym)
        for i in range(len(words) - n + 1):
            window = words[i : i + n]
            if "".join(w[0] for w in window) == acronym:
                covered.update(window)
    return covered


def missing_elements(
    contract: SeedContract, question: str, answer_key: str = ""
) -> tuple[list[str], dict[str, str]]:
    """Required elements the candidate no longer contains, and how the others matched.

    A term counts as present when the question contains it (by stem, abbreviation or
    acronym) or contains a NEW word that means the same. A word the seed itself uses
    can never stand in for a different seed term, so "TCP" does not cover "congestion".
    A term found only in the answer key also counts: "which kind of testing is this?"
    assesses integration testing without naming it in the question.
    """
    cand = candidate_terms(question)
    cand_stems = {stem(t) for t in cand}
    acronyms = _acronym_covered(contract.task, question)
    how: dict[str, str] = {}
    unresolved: list[str] = []
    for term in contract.required_elements:
        if _lexically_present(term, cand, cand_stems):
            how[term] = "present"
        elif term in acronyms:
            how[term] = "acronym"
        else:
            unresolved.append(term)

    if unresolved and cand:
        seed_stems = {stem(t) for t in content_tokens(contract.task)}
        fresh = [t for t in cand if stem(t) not in seed_stems]
        if fresh:
            sims = embeddings.similarity_matrix(unresolved, fresh)
            for i, term in enumerate(list(unresolved)):
                j = int(np.argmax(sims[i]))
                if float(sims[i][j]) >= SOFT_MATCH_MIN:
                    how[term] = f"synonym: {fresh[j]} ({float(sims[i][j]):.2f})"
                    unresolved.remove(term)

    # In a coding task a named technology is the language of the answer ("a SQL
    # query", "an HTML form") and may not be swapped. Elsewhere a name is immutable
    # only when it is one of the concept-bearing terms above ("TCP" is; the "CPU" in
    # "CPU scheduling" is a modifier a faithful variation may leave out).
    missing_named = [
        name for name in (contract.named_elements if contract.task_type == "coding" else [])
        if not re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", question or "", re.I)
    ]
    if answer_key and (unresolved or missing_named):
        key_terms = candidate_terms(answer_key)
        key_stems = {stem(t) for t in key_terms}
        for term in list(unresolved):
            if _lexically_present(term, key_terms, key_stems):
                how[term] = "in answer key"
                unresolved.remove(term)
        for name in list(missing_named):
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", answer_key, re.I):
                how[name] = "in answer key"
                missing_named.remove(name)

    for name in missing_named:
        how[name] = "missing"
    for term in unresolved:
        how[term] = "missing"
    return unresolved + missing_named, how
