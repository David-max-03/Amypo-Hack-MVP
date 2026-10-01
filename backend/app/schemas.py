"""Pydantic request/response models.

The PS8 and PS2 problem statements each specify an exact API contract. Those
contracts are honoured literally (same field names, same verdict strings); any extra
fields we return are additive so a strict client can ignore them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Verdict = Literal[
    "trustworthy", "partially_reliable", "misleading", "fabricated", "unverifiable"
]
Decision = Literal["PASS", "REVIEW", "REJECT"]
DifficultyLabel = Literal["easy", "medium", "hard", "expert"]


# ======================================================================
# PS8 - seed / generation
# ======================================================================
class SeedMetadata(BaseModel):
    """What the Seed Parser extracts from a raw seed question."""

    domain: str
    topic: str
    subtopic: str | None = None
    core_concept: str
    question_type: str
    difficulty: DifficultyLabel
    difficulty_score: float = Field(ge=0.0, le=1.0)
    learning_objective: str
    keywords: list[str] = Field(default_factory=list)
    raw_seed: str


class VariationPlanItem(BaseModel):
    """One planned variation: which strategy to apply, and how."""

    index: int
    strategy: str
    strategy_label: str
    instruction: str
    preserve: list[str]
    change: list[str]
    # Solution-method axis (coding only); None when the seed has no method axis.
    method: str | None = None
    method_label: str = ""
    method_instruction: str = ""


class TestCase(BaseModel):
    input: str = ""
    expected_output: str = ""


class Candidate(BaseModel):
    """A generated question candidate before (or after) validation."""

    id: str
    question: str
    answer_key: str
    domain: str
    topic: str
    subtopic: str | None = None
    difficulty: DifficultyLabel
    difficulty_score: float = Field(default=0.5, ge=0.0, le=1.0)
    question_type: str
    learning_objective: str
    test_cases: list[TestCase] = Field(default_factory=list)
    variation_strategy: str
    strategy_label: str = ""
    solution_method: str | None = None
    # Provenance so the UI can show where a candidate came from.
    attempt: int = 0
    regenerated: bool = False
    raw_model_output: str | None = None
    parse_warnings: list[str] = Field(default_factory=list)


# ======================================================================
# PS8 - structural validation
# ======================================================================
class StructuralValidation(BaseModel):
    concept_preserved: bool
    difficulty_match: bool
    is_duplicate: bool
    meaningful_variation: bool
    passed: bool
    semantic_similarity: float = Field(ge=0.0, le=1.0)
    lexical_similarity: float = Field(ge=0.0, le=1.0)
    concept_overlap: float = Field(ge=0.0, le=1.0)
    difficulty_delta: float
    nearest_match: str | None = None
    nearest_match_source: str | None = None
    reasons: list[str] = Field(default_factory=list)
    checks: dict[str, Any] = Field(default_factory=dict)


# ======================================================================
# PS2 - reliability verification
# ======================================================================
class FlaggedSpan(BaseModel):
    """Exactly the shape PS2's API contract requires, plus optional offsets."""

    text: str
    reason: str
    # Additive fields - a strict PS2 client can ignore these.
    start: int | None = None
    end: int | None = None
    severity: Literal["low", "medium", "high"] = "medium"
    claim_type: str | None = None
    best_evidence: str | None = None
    best_similarity: float | None = None


class EvidenceItem(BaseModel):
    claim: str
    supported: bool
    status: Literal["supported", "partially_supported", "unsupported", "contradicted"]
    similarity: float
    keyword_grounding: float
    source_id: str | None = None
    source_title: str | None = None
    source_text: str | None = None


class Claim(BaseModel):
    text: str
    claim_type: Literal["factual", "answer", "citation", "assumption", "opinion", "inference"]
    start: int
    end: int


class ReliabilityVerification(BaseModel):
    reliability_score: float = Field(ge=0.0, le=1.0)
    confidence_score: float = Field(ge=0.0, le=1.0)
    hallucination_probability: float = Field(ge=0.0, le=1.0)
    verdict: Verdict
    flagged_spans: list[FlaggedSpan] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    signals: dict[str, float] = Field(default_factory=dict)
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    # Honesty: which embedding backend actually produced these numbers.
    embedding_backend: str = ""
    self_consistency_used: bool = False
    timings_ms: dict[str, float] = Field(default_factory=dict)


# ======================================================================
# Decision engine
# ======================================================================
class DecisionResult(BaseModel):
    decision: Decision
    reasons: list[str] = Field(default_factory=list)
    structural_validation: StructuralValidation | None = None
    reliability_verification: ReliabilityVerification | None = None


class PipelineCandidate(BaseModel):
    """A candidate plus everything both gates concluded about it."""

    candidate: Candidate
    decision: Decision
    decision_reasons: list[str] = Field(default_factory=list)
    structural_validation: StructuralValidation | None = None
    reliability_verification: ReliabilityVerification | None = None
    status: Literal[
        "generated", "validated", "verified", "accepted", "rejected", "review"
    ] = "generated"
    attempts: int = 1
    regeneration_history: list[dict[str, Any]] = Field(default_factory=list)
    # The subject area the user picked (e.g. "algorithms"); the pipeline domain above
    # stays the one PS8/PS2 validate against.
    subject_area: str | None = None


# ======================================================================
# API - PS8 /generate
# ======================================================================
class GenerateRequest(BaseModel):
    seed_question: str = Field(min_length=5)
    domain: str = "programming"
    count: int = Field(default=10, ge=1, le=60)
    difficulty_shift: DifficultyLabel | None = Field(
        default=None,
        description="Request an explicit difficulty shift. None preserves the seed's.",
    )
    regenerate: bool = Field(
        default=True,
        description=(
            "Regenerate structurally rejected candidates from their rejection reasons, "
            "up to max_regeneration_attempts each."
        ),
    )


class GenerateVariation(BaseModel):
    """PS8's required response item, with our additive metadata."""

    question: str
    answer_key: str
    difficulty: float  # PS8 contract: numeric 0..1
    # Additive
    id: str
    difficulty_label: DifficultyLabel
    domain: str
    topic: str
    subtopic: str | None = None
    question_type: str
    learning_objective: str
    test_cases: list[TestCase] = Field(default_factory=list)
    variation_strategy: str
    strategy_label: str = ""
    solution_method: str | None = None
    structural_validation: StructuralValidation | None = None


class GenerateResponse(BaseModel):
    variations: list[GenerateVariation]
    duplicate_rate: float
    # Additive
    requested_count: int
    generated_count: int
    accepted_count: int
    rejected_count: int
    regeneration_attempts: int = 0
    regenerated_accepted: int = 0
    seed_metadata: SeedMetadata | None = None
    rejected: list[dict[str, Any]] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


# ======================================================================
# API - PS2 /verify
# ======================================================================
class VerifyRequest(BaseModel):
    response_text: str = Field(min_length=1)
    source_context: list[str] = Field(default_factory=list)
    question: str | None = Field(
        default=None, description="Optional question the text is answering."
    )


class VerifyResponse(BaseModel):
    """PS2's required response shape (additive fields included)."""

    reliability_score: float
    hallucination_probability: float
    verdict: Verdict
    flagged_spans: list[FlaggedSpan]
    # Additive
    confidence_score: float
    evidence: list[EvidenceItem] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    signals: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    embedding_backend: str = ""
    analysis_time_ms: float = 0.0
    within_latency_budget: bool = True


# ======================================================================
# API - integrated /generate-and-verify
# ======================================================================
class GenerateAndVerifyRequest(BaseModel):
    seed_question: str = Field(min_length=5)
    domain: str = "programming"
    count: int = Field(default=5, ge=1, le=60)
    difficulty_shift: DifficultyLabel | None = None
    enable_regeneration: bool = True
    persist: bool = Field(
        default=True, description="Write accepted/review results to local JSON stores."
    )
    job_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_-]{1,64}$",
        description="Optional client-chosen id; poll GET /progress/{job_id} while it runs.",
    )


class PipelineSummary(BaseModel):
    requested: int
    generated: int
    passed: int
    review: int
    rejected: int
    duplicate_rate: float
    regeneration_attempts: int
    mean_reliability_score: float
    flagged_span_count: int


class GenerateAndVerifyResponse(BaseModel):
    seed_metadata: SeedMetadata | None = None
    results: list[PipelineCandidate]
    summary: PipelineSummary
    timings_ms: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    # Set only by POST /demo/run: scripted candidates, real validation, never persisted.
    demo: bool = False
    demo_label: str | None = None
    demo_description: str | None = None


class JobRequest(BaseModel):
    """Start a background generate-and-verify job (POST /jobs)."""

    seed_question: str = Field(min_length=5)
    domain: str = "programming"
    subject_area: str | None = Field(
        default=None, description="Taxonomy subject area; overrides `domain` with its pipeline domain."
    )
    count: int = Field(default=10, ge=1, le=60)
    difficulty_shift: DifficultyLabel | None = None
    enable_regeneration: bool = True
    persist: bool = True


class DemoRunRequest(BaseModel):
    job_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")


# ======================================================================
# API - health / domains
# ======================================================================
class DomainInfo(BaseModel):
    id: str
    label: str
    description: str
    example_seed: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    ollama: dict[str, Any]
    embeddings: dict[str, Any]
    corpus: dict[str, Any]
    storage: dict[str, Any]
    config: dict[str, Any]
