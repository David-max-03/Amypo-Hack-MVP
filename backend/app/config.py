"""
Central configuration for the Code Titans PS8 + PS2 pipeline.

Every tunable threshold, weight and limit in the system lives in this file so that
judges (and we) can see and change the trust policy in one place. Nothing else in
the codebase is allowed to hard-code a threshold.

Any field can be overridden with an environment variable using the AMYPO_ prefix,
e.g. AMYPO_DUPLICATE_SEMANTIC_MAX=0.75 or AMYPO_OLLAMA_MODEL=qwen2.5-coder:7b
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root: backend/app/config.py -> backend/app -> backend -> <root>
ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AMYPO_",
        env_file=str(ROOT_DIR / ".env"),
        extra="ignore",
        protected_namespaces=(),
    )

    # ------------------------------------------------------------------
    # Paths / storage (PS8 + PS2 use plain local JSON for the MVP)
    # ------------------------------------------------------------------
    data_dir: Path = ROOT_DIR / "data"

    # ------------------------------------------------------------------
    # Ollama / local generation model  (PS8 constraint: no paid APIs)
    # ------------------------------------------------------------------
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b"
    ollama_timeout_s: float = 180.0
    # Transient Ollama 5xx responses are retried before the call is treated as failed.
    ollama_server_error_retries: int = 2
    ollama_server_error_backoff_s: float = 2.0
    # Generation sampling. Higher temperature => more surface diversity, which is
    # what PS8's distinctness rubric rewards.
    generation_temperature: float = 0.85
    generation_top_p: float = 0.95
    # A regeneration attempt is deliberately cooler: we want it to *fix* things.
    regeneration_temperature: float = 0.6
    # A variation is ~250 output tokens now the model no longer echoes metadata;
    # the cap only bounds runaway output.
    max_generation_tokens: int = 600
    # Concurrent generation requests per wave. Only helps when Ollama runs with
    # OLLAMA_NUM_PARALLEL >= this value; otherwise Ollama queues them and total time
    # is unchanged. Candidates in one wave cannot see each other, so duplicates
    # between them are left to the duplicate validator and regeneration.
    generation_concurrency: int = 1
    # An unparseable generation is retried this many times before it is recorded as
    # a failure. Retries run cooler and with more headroom, because the usual cause
    # is JSON truncated at the token limit once the answer key contains code.
    parse_retry_attempts: int = 1
    parse_retry_max_tokens: int = 900
    # Non-coding answer keys shorter than this are treated as stubs, not answers.
    answer_key_min_words: int = 3

    # ------------------------------------------------------------------
    # PS2 embedding model (local, CPU, no paid APIs)
    # ------------------------------------------------------------------
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    # If sentence-transformers / torch cannot be imported, the system falls back to
    # a deterministic lexical vectoriser. That fallback is clearly reported through
    # /api/v1/health so we never silently claim MiniLM was used.
    allow_embedding_fallback: bool = True
    # Local natural-language-inference model: decides whether a corpus sentence
    # entails or contradicts a claim. Without it PS2 falls back to similarity +
    # keyword grounding, which cannot tell a statement from its opposite.
    entailment_enabled: bool = True
    entailment_model: str = "cross-encoder/nli-MiniLM2-L6-H768"
    # A corpus sentence supports (or contradicts) a claim at or above this probability.
    entailment_decision_min: float = 0.80
    # Calling a claim contradicted is held to a higher standard than calling it
    # unconfirmed: this probability, from the corpus sentence closest to the claim,
    # which must also contain this share of the claim's content words.
    entailment_contradiction_min: float = 0.90
    entailment_contradiction_overlap: float = 0.50
    # Only corpus sentences at least this similar to the claim are read at all.
    entailment_min_similarity: float = 0.50

    # ------------------------------------------------------------------
    # PS8 structural validation thresholds
    # ------------------------------------------------------------------
    # Cosine similarity at or above this against any known question => duplicate.
    duplicate_semantic_max: float = 0.86
    # Token Jaccard at or above this => duplicate (catches near-verbatim copies).
    duplicate_lexical_max: float = 0.75
    # A candidate must share at least this much concept overlap with the seed,
    # otherwise it is testing something else entirely (concept drift).
    concept_min_overlap: float = 0.18
    # Fallback for a scenario variation that legitimately shares few words with the
    # seed: it may still pass on semantic similarity to the learning objective alone.
    # This floor is deliberately well above the ~0.2 MiniLM assigns to unrelated
    # text, or genuinely off-topic questions would slip through.
    concept_min_semantic: float = 0.40
    # A candidate that is *too* similar to the seed is a paraphrase, not a
    # variation. Above this it fails the "meaningful variation" check.
    variation_similarity_max: float = 0.80
    # A variation that verifiably changes the solution method (recursion instead of
    # a loop, say) is meaningful even when its wording stays close to the seed, so it
    # may reach this similarity. It still has to pass the duplicate check.
    method_variation_similarity_max: float = 0.86
    # ...and one that is too far away has lost the learning objective.
    variation_similarity_min: float = 0.10
    # Difficulty is scored 0..1; a variation may drift by at most this much from
    # the seed unless the caller explicitly requests a shift.
    difficulty_tolerance: float = 0.20

    # ------------------------------------------------------------------
    # PS2 reliability scoring weights (must sum to 1.0; validated at startup)
    # ------------------------------------------------------------------
    w_source_grounding: float = 0.30
    w_non_hallucination: float = 0.30
    w_factual_consistency: float = 0.20
    w_non_contradiction: float = 0.15
    w_answer_completeness: float = 0.05

    # ------------------------------------------------------------------
    # PS2 source verification
    # ------------------------------------------------------------------
    # A claim is "supported" when its best corpus match is at least this similar.
    claim_support_threshold: float = 0.55
    # Between weak and support it is "partially supported" (=> unverifiable-ish).
    claim_weak_threshold: float = 0.38
    # Keyword grounding: fraction of a claim's content words that must appear in
    # the matched evidence. Semantic similarity alone is never treated as proof.
    claim_keyword_overlap_min: float = 0.25
    # How many corpus entries to retrieve per claim.
    evidence_top_k: int = 3

    # ------------------------------------------------------------------
    # PS2 hallucination detector
    # ------------------------------------------------------------------
    # Self-consistency: how many extra samples to draw from Ollama. The technical
    # doc caps this at 3 to stay inside the <10s budget. 0 disables sampling.
    self_consistency_samples: int = 0
    self_consistency_timeout_s: float = 6.0
    # Below this agreement across samples the answer is treated as unstable.
    self_consistency_min_agreement: float = 0.55

    # ------------------------------------------------------------------
    # PS2 verdict bands (on reliability_score)
    # ------------------------------------------------------------------
    verdict_trustworthy_min: float = 0.75
    verdict_partially_reliable_min: float = 0.55
    verdict_misleading_min: float = 0.35
    # Below verdict_misleading_min => "fabricated", unless the evidence base was
    # too thin to judge at all, in which case => "unverifiable".
    unverifiable_max_supported_ratio: float = 0.20

    # ------------------------------------------------------------------
    # Decision engine
    # ------------------------------------------------------------------
    pass_reliability_min: float = 0.70
    review_reliability_min: float = 0.45
    pass_max_hallucination_probability: float = 0.35

    # ------------------------------------------------------------------
    # Regeneration loop
    # ------------------------------------------------------------------
    max_regeneration_attempts: int = 2

    # ------------------------------------------------------------------
    # Limits / performance
    # ------------------------------------------------------------------
    max_variations_per_request: int = 60
    ps2_target_latency_s: float = 10.0
    log_timings: bool = True

    # ------------------------------------------------------------------
    # Derived paths
    # ------------------------------------------------------------------
    @property
    def question_bank_path(self) -> Path:
        return self.data_dir / "question_bank.json"

    @property
    def review_queue_path(self) -> Path:
        return self.data_dir / "review_queue.json"

    @property
    def validation_report_path(self) -> Path:
        return self.data_dir / "validation_report.json"

    @property
    def audit_logs_path(self) -> Path:
        return self.data_dir / "audit_logs.json"

    @property
    def reference_corpus_path(self) -> Path:
        return self.data_dir / "reference_corpus.json"

    @property
    def reliability_weights(self) -> dict[str, float]:
        return {
            "source_grounding": self.w_source_grounding,
            "non_hallucination": self.w_non_hallucination,
            "factual_consistency": self.w_factual_consistency,
            "non_contradiction": self.w_non_contradiction,
            "answer_completeness": self.w_answer_completeness,
        }

    def validate_weights(self) -> None:
        total = sum(self.reliability_weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"PS2 reliability weights must sum to 1.0, got {total:.6f}. "
                "Fix the w_* values in backend/app/config.py or the AMYPO_W_* env vars."
            )


settings = Settings()
settings.validate_weights()
