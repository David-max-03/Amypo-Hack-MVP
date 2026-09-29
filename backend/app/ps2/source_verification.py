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

Absence of evidence is not evidence of falsehood. A claim the corpus cannot speak
to is marked `unsupported` and routed to REVIEW - never called false.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..config import settings
from ..core.embeddings import embeddings
from ..core.storage import read_json
from ..core.text_utils import keyword_grounding
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

    @property
    def supported(self) -> bool:
        return self.status == "supported"


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
