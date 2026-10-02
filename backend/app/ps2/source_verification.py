"""Source Verification Layer (PS2).

Checks each claim against the trusted LOCAL reference corpus. Two signals are
combined and BOTH matter:

  * MiniLM cosine similarity - does the corpus say something about this?
  * keyword grounding        - do the claim's actual content words appear in the
                               matched evidence?

The technical documentation is explicit that semantic similarity alone must never
be treated as proof of factual correctness: "O(1) space" and "O(n) space" embed
almost identically, so a similarity-only checker would wave through a wrong
complexity claim. Requiring lexical grounding as well is what catches it.

Those two signals say the corpus talks about the same thing in the same words.
They cannot say whether it AGREES: "TCP is a connectionless protocol" matches the
entry stating TCP is connection-oriented on both. So when the local entailment
model is available, a factual claim is "supported" only if a corpus sentence about
the same subject entails it, and "contradicted" if such a sentence says the
opposite. Similarity and keywords then only choose which sentences are read.

Absence of evidence is not evidence of falsehood. A claim the corpus cannot speak
to is marked `unsupported` and routed to REVIEW - never called false.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..config import settings


from ..core.embeddings import embeddings
from ..core.entailment import entailment
from ..core.storage import read_json
from ..core.text_utils import content_tokens, keyword_grounding, light_stem, split_sentences
from ..schemas import Claim, EvidenceItem

logger = logging.getLogger(__name__)


@dataclass
class CorpusEntry:
    id: str
    title: str
    text: str
    domain: str
    source: str
    tags: list[str] = field(default_factory=list)

    @property
    def searchable(self) -> str:
        return f"{self.title}. {self.text}"


class ReferenceCorpus:
    """The local grounding knowledge base, loaded once and cached."""

    def __init__(self) -> None:
        self._entries: list[CorpusEntry] | None = None

    def load(self, force: bool = False) -> list[CorpusEntry]:
        if self._entries is not None and not force:
            return self._entries

        raw = read_json("reference_corpus.json", {"entries": []})
        entries: list[CorpusEntry] = []
        for item in raw.get("entries", []):
            if not item.get("text"):
                continue
            entries.append(
                CorpusEntry(
                    id=str(item.get("id", f"entry-{len(entries)}")),
                    title=str(item.get("title", "")),
                    text=str(item["text"]),
                    domain=str(item.get("domain", "general")),
                    source=str(item.get("source", "local reference corpus")),
                    tags=list(item.get("tags", [])),
                )
            )
        self._entries = entries
        logger.info("Loaded %d reference corpus entries", len(entries))
        return entries

    def stats(self) -> dict[str, Any]:
        entries = self.load()
        domains: dict[str, int] = {}
        for e in entries:
            domains[e.domain] = domains.get(e.domain, 0) + 1
        return {"entry_count": len(entries), "domains": domains}

    def reset(self) -> None:
        self._entries = None


corpus = ReferenceCorpus()


@dataclass
class ClaimVerification:
    claim: Claim
    status: str  # supported | partially_supported | unsupported | contradicted
    similarity: float
    keyword_grounding: float
    entry: CorpusEntry | None
    detail: str
    # Set when the entailment model judged the claim: the corpus sentence it was
    # judged against, and what conflicted when the status is "contradicted".
    evidence_sentence: str | None = None
    conflict: str | None = None
    judged_by: str = "similarity"

    @property
    def supported(self) -> bool:
        return self.status == "supported"


_CHECKABLE = {"factual", "answer", "citation"}
_BIG_O_RE = re.compile(r"o\(\s*([^)]{1,20}?)\s*\)", re.I)
_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def _specifics(text: str) -> tuple[set[str], set[str]]:
    """(Big-O terms, other numbers) a sentence commits to."""
    big_o = {re.sub(r"[\s*]", "", m.lower()) for m in _BIG_O_RE.findall(text)}
    return big_o, set(_NUMBER_RE.findall(_BIG_O_RE.sub(" ", text)))


def _states_the_same_specifics(claim: str, sentence: str) -> bool:
    """Every complexity and number in the claim must be in the sentence that supports
    it. The entailment model reads "32 bits" and "128 bits" as near-equivalent."""
    claim_o, claim_n = _specifics(claim)
    sent_o, sent_n = _specifics(sentence)
    return claim_o <= sent_o and claim_n <= sent_n


def _judge_by_entailment(
    claim: Claim, entries: list[CorpusEntry | None]
) -> ClaimVerification | None:
    """Decide support from what the corpus sentences about the claim's subject say.

    Returns None when there is nothing to read (no sentence about the same subject
    is close enough), which leaves the claim to the similarity rule - capped below
    "supported", because nothing confirmed it.
    """
    from .contradiction import complexity_conflict  # local import avoids a cycle

    pool = [(e, sent) for e in entries if e is not None for sent in split_sentences(e.text)]
    tokens = content_tokens(claim.text)
    if not pool or not tokens:
        return None
    subject = light_stem(tokens[0])
    sentences = [sent for _, sent in pool]
    sims = embeddings.similarity_matrix([claim.text], sentences)[0]
    read = [
        (pool[i][0], sentences[i], float(sims[i]))
        for i in range(len(sentences))
        if float(sims[i]) >= settings.entailment_min_similarity
        and any(light_stem(t) == subject for t in content_tokens(sentences[i]))
    ]
    if not read:
        return None
    read.sort(key=lambda r: -r[2])
    read = read[:6]

    def result(status: str, entry, sentence: str, sim: float, detail: str, conflict: str | None = None):
        return ClaimVerification(
            claim=claim, status=status, similarity=round(sim, 4),
            keyword_grounding=round(keyword_grounding(claim.text, sentence), 4),
            entry=entry, detail=detail, evidence_sentence=sentence, conflict=conflict,
            judged_by="entailment",
        )

    # A stated complexity is compared by rule: the model cannot read Big-O.
    for entry, sentence, sim in read:
        reason = complexity_conflict(claim.text, sentence)
        if reason:
            return result("contradicted", entry, sentence, sim,
                          f"conflicts with '{entry.title}' ({entry.source}): {reason}", reason)

    scores = entailment.judge([sentence for _, sentence, _ in read], claim.text)
    threshold = settings.entailment_decision_min
    supporting = [
        (r, ent) for r, (ent, _con) in zip(read, scores)
        # `claim_support_threshold` still gates support: a sentence that is not close
        # enough to the claim cannot confirm it, whatever the model says.
        if ent >= threshold and r[2] >= settings.claim_support_threshold
        and _states_the_same_specifics(claim.text, r[1])
    ]
    opposing = [(r, con) for r, (_ent, con) in zip(read, scores) if con >= threshold]
    has_complexity = bool(_BIG_O_RE.search(claim.text))

    if has_complexity:
        # For a complexity claim the rule above has already compared the Big-O terms;
        # the model's "contradiction" between two complexities is not reliable.
        opposing = []
    if supporting and opposing:
        # The corpus has a sentence that agrees and one that disagrees - typically the
        # entry also describes a sibling concept (TCP next to UDP). The sentence
        # closest to the claim is the one about the claim; if it takes neither side,
        # nothing is confirmed and a person decides.
        closest = read[0]
        if any(r == closest for r, _ in supporting) and not any(r == closest for r, _ in opposing):
            opposing = []
        elif any(r == closest for r, _ in opposing) and not any(r == closest for r, _ in supporting):
            supporting = []
        else:
            (entry, sentence, sim), _ = supporting[0]
            return result("partially_supported", entry, sentence, sim,
                          f"'{entry.title}' has sentences that both agree and disagree with "
                          "this claim, so it is not confirmed")

    if supporting:
        (entry, sentence, sim), ent = max(supporting, key=lambda x: x[1])
        return result("supported", entry, sentence, sim,
                      f"entailed by '{entry.title}' ({entry.source}): \"{sentence}\" "
                      f"(entailment {ent:.2f})")
    if opposing:
        (entry, sentence, sim), con = max(opposing, key=lambda x: x[1])
        # Calling a claim wrong needs more than calling it unconfirmed. The sentence
        # must be the one closest to the claim, share most of its words, and
        # contradict it firmly - the model also reports confident "contradictions"
        # against neighbouring sentences about a sibling concept.
        if (
            (entry, sentence, sim) == read[0]
            and con >= settings.entailment_contradiction_min
            and keyword_grounding(claim.text, sentence) >= settings.entailment_contradiction_overlap
        ):
            return result("contradicted", entry, sentence, sim,
                          f"contradicted by '{entry.title}' ({entry.source}): \"{sentence}\" "
                          f"(contradiction {con:.2f})",
                          f"the entry states \"{sentence}\"")
    entry, sentence, sim = read[0]
    return result("partially_supported", entry, sentence, sim,
                  f"'{entry.title}' discusses this ({sim:.2f} similarity) but no sentence in "
                  "it confirms the claim")


def _candidate_pool(
    domain: str | None, extra_context: list[str] | None
) -> tuple[list[str], list[CorpusEntry | None]]:
    """Build the searchable text pool: caller-supplied context first, then corpus.

    Caller-supplied `source_context` is treated as trusted evidence for this request
    only - that is what PS2's API contract means by the optional source_context field.
    """
    texts: list[str] = []
    origins: list[CorpusEntry | None] = []

    for i, ctx in enumerate(extra_context or []):
        if ctx and ctx.strip():
            texts.append(ctx.strip())
            origins.append(
                CorpusEntry(
                    id=f"request-context-{i}",
                    title="Caller-supplied source context",
                    text=ctx.strip(),
                    domain=domain or "request",
                    source="source_context supplied with the request",
                )
            )

    entries = corpus.load()
    # Prefer the matching domain but never exclude the rest: a claim can legitimately
    # be grounded by an entry filed under another domain.
    if domain:
        entries = sorted(entries, key=lambda e: 0 if e.domain == domain else 1)

    for entry in entries:
        texts.append(entry.searchable)
        origins.append(entry)

    return texts, origins


def verify_claim(
    claim: Claim,
    *,
    domain: str | None = None,
    extra_context: list[str] | None = None,
) -> ClaimVerification:
    """Ground one claim against the corpus using similarity AND keyword overlap."""
    texts, origins = _candidate_pool(domain, extra_context)

    if not texts:
        return ClaimVerification(
            claim=claim,
            status="unsupported",
            similarity=0.0,
            keyword_grounding=0.0,
            entry=None,
            detail="the reference corpus is empty, so no claim could be grounded",
        )

    scores = embeddings.similarity_matrix([claim.text], texts)[0]

    # Rank by the combined signal, not similarity alone, so the evidence we report is
    # the entry that actually shares vocabulary with the claim.
    ranked = sorted(
        range(len(texts)),
        key=lambda i: (0.65 * float(scores[i]) + 0.35 * keyword_grounding(claim.text, texts[i])),
        reverse=True,
    )[: max(1, settings.evidence_top_k)]

    use_entailment = claim.claim_type in _CHECKABLE and entailment.available
    if use_entailment:
        judged = _judge_by_entailment(claim, [origins[i] for i in ranked])
        if judged is not None:
            return judged

    best_idx = ranked[0]
    similarity = float(scores[best_idx])
    grounding = keyword_grounding(claim.text, texts[best_idx])
    entry = origins[best_idx]

    if similarity >= settings.claim_support_threshold:
        if grounding >= settings.claim_keyword_overlap_min:
            status = "supported"
            detail = (
                f"grounded in '{entry.title}' ({entry.source}) with {similarity:.2f} "
                f"semantic similarity and {grounding:.2f} keyword overlap"
                if entry
                else f"grounded with {similarity:.2f} similarity"
            )
        else:
            # Topically close but the specifics do not line up - the classic signature
            # of a fabricated detail inserted into a familiar-sounding sentence.
            status = "partially_supported"
            detail = (
                f"the corpus discusses this topic ('{entry.title}') at {similarity:.2f} "
                f"similarity, but only {grounding:.2f} of the claim's specific terms "
                f"appear in that evidence (need {settings.claim_keyword_overlap_min:.2f}), "
                "so the specific details are not confirmed"
                if entry
                else "topically close but specific terms are not confirmed"
            )
    elif similarity >= settings.claim_weak_threshold:
        status = "partially_supported"
        detail = (
            f"only weakly related to '{entry.title}' ({similarity:.2f} similarity, "
            f"below the {settings.claim_support_threshold:.2f} support threshold)"
            if entry
            else f"weak evidence only ({similarity:.2f} similarity)"
        )
    else:
        status = "unsupported"
        detail = (
            f"no entry in the local reference corpus covers this claim "
            f"(best match {similarity:.2f}, below {settings.claim_weak_threshold:.2f}). "
            "The corpus is incomplete, so this is unverifiable rather than false."
        )

    if use_entailment and status == "supported":
        # Words matched, but no corpus sentence about the claim's subject was close
        # enough to read, so nothing actually confirmed it.
        status = "partially_supported"
        detail = (
            f"shares vocabulary with '{entry.title}' ({similarity:.2f} similarity) but no "
            "corpus sentence about the same subject confirms it"
            if entry else "matched by vocabulary only; not confirmed"
        )

    return ClaimVerification(
        claim=claim,
        status=status,
        similarity=round(similarity, 4),
        keyword_grounding=round(grounding, 4),
        entry=entry,
        detail=detail,
    )


def verify_claims(
    claims: list[Claim],
    *,
    domain: str | None = None,
    extra_context: list[str] | None = None,
) -> list[ClaimVerification]:
    return [
        verify_claim(c, domain=domain, extra_context=extra_context) for c in claims
    ]


def to_evidence(results: list[ClaimVerification]) -> list[EvidenceItem]:
    return [
        EvidenceItem(
            claim=r.claim.text,
            supported=r.supported,
            status=r.status,  # type: ignore[arg-type]
            similarity=r.similarity,
            keyword_grounding=r.keyword_grounding,
            source_id=r.entry.id if r.entry else None,
            source_title=r.entry.title if r.entry else None,
            source_text=(r.entry.text[:400] if r.entry else None),
        )
        for r in results
    ]
