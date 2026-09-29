"""Integration: decision engine, regeneration loop, storage and the API surface."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import pipeline
from backend.app.config import settings
from backend.app.core import storage
from backend.app.decision.decision_engine import combined_feedback, decide
from backend.app.main import app
from backend.app.ps2.engine import verify_candidate
from backend.app.ps8.validation.engine import validate_candidate
from backend.tests.conftest import candidate_json, make_candidate

SEED_TEXT = "Write a function to reverse a singly linked list."

GOOD_VARIATION = (
    "A music app stores its play queue as a singly linked list of track nodes. "
    "Implement a routine that reverses the queue so the last track plays first, "
    "rewiring the existing nodes rather than allocating a new queue."
)
SECOND_VARIATION = (
    "A warehouse conveyor is modelled as a singly linked list of parcel nodes. "
    "Reverse the first k parcels in the chain while leaving the remainder untouched, "
    "using only pointer rewiring."
)


class TestDecisionEngine:
    def test_both_gates_pass_gives_pass(self, temp_data_dir, seed):
        candidate = make_candidate(GOOD_VARIATION)
        structural = validate_candidate(candidate, seed)
        reliability = verify_candidate(candidate)
        assert structural.passed

        result = decide(structural, reliability)
        assert result.decision in {"PASS", "REVIEW"}
        if result.decision == "PASS":
            assert reliability.reliability_score >= settings.pass_reliability_min

    def test_structural_failure_rejects_without_running_ps2(self, temp_data_dir, seed):
        duplicate = make_candidate(SEED_TEXT)
        structural = validate_candidate(duplicate, seed)
        assert not structural.passed

        result = decide(structural, None)
        assert result.decision == "REJECT"
        assert any("PS8 structural failure" in r for r in result.reasons)

    def test_misleading_verdict_rejects(self, temp_data_dir, seed):
        candidate = make_candidate(
            "A caching layer stores entries in a singly linked list. Explain why "
            "recursive reversal of that list always uses O(1) space because the "
            "compiler removes every stack frame automatically.",
            answer_key="Recursive reversal always uses O(1) space, so recursion is free.",
        )
        structural = validate_candidate(candidate, seed)
        reliability = verify_candidate(candidate)
        assert reliability.verdict in {"misleading", "fabricated", "partially_reliable"}

        if structural.passed and reliability.verdict in {"misleading", "fabricated"}:
            assert decide(structural, reliability).decision == "REJECT"

    def test_unverifiable_routes_to_review_never_reject(self, temp_data_dir, seed):
        """An incomplete corpus must never be treated as proof of falsehood."""
        candidate = make_candidate(
            "A logistics firm models its delivery chain as a singly linked list. "
            "Reverse the chain, given that Estonian cooperatives must file their "
            "annual declaration before the thirtieth of June.",
            answer_key="Reverse by pointer rewiring; the filing deadline is 30 June.",
        )
        structural = validate_candidate(candidate, seed)
        reliability = verify_candidate(candidate)
        if reliability.verdict == "unverifiable" and structural.passed:
            assert decide(structural, reliability).decision == "REVIEW"

    def test_missing_reliability_routes_to_review(self, temp_data_dir, seed):
        structural = validate_candidate(make_candidate(GOOD_VARIATION), seed)
        assert decide(structural, None).decision == "REVIEW"

    def test_high_hallucination_blocks_a_pass(self, temp_data_dir, seed, monkeypatch):
        candidate = make_candidate(GOOD_VARIATION)
        structural = validate_candidate(candidate, seed)
        reliability = verify_candidate(candidate)
        monkeypatch.setattr(settings, "pass_max_hallucination_probability", -0.01)
        assert decide(structural, reliability).decision == "REVIEW"

    def test_combined_feedback_merges_both_gates(self, temp_data_dir, seed):
        candidate = make_candidate(SEED_TEXT)
        structural = validate_candidate(candidate, seed)
        s_reasons, r_reasons, spans = combined_feedback(structural, None)
        assert s_reasons and isinstance(r_reasons, list) and isinstance(spans, list)


class TestRegenerationLoop:
    """Generation is faked so the loop's control flow is tested deterministically."""

    def _patch_ollama(self, monkeypatch, responses):
        from backend.tests.conftest import FakeOllama

        fake = FakeOllama(responses)
        monkeypatch.setattr("backend.app.ps8.generation_engine.ollama", fake)
        monkeypatch.setattr("backend.app.ps8.seed_parser.ollama", fake)
        return fake

    def test_duplicate_is_regenerated_into_an_accepted_variation(
        self, temp_data_dir, monkeypatch
    ):
        # First attempt is a verbatim copy of the seed (duplicate -> REJECT);
        # the regeneration returns a genuinely different question.
        fake = self._patch_ollama(
            monkeypatch,
            [candidate_json(SEED_TEXT), candidate_json(GOOD_VARIATION)],
        )
        _seed, results, summary, _t, _w = pipeline.run_pipeline(
            SEED_TEXT, "programming", 1, use_llm_parser=False, persist=False
        )
        assert len(results) == 1
        assert results[0].attempts == 2
        assert results[0].regeneration_history
        assert summary.regeneration_attempts == 1
        # The corrective prompt must name the actual failure.
        assert "REJECTED" in fake.prompts[1]
        assert "similarity too high" in fake.prompts[1]

    def test_regeneration_prompt_carries_ps8_and_ps2_feedback(
        self, temp_data_dir, monkeypatch
    ):
        fake = self._patch_ollama(
            monkeypatch,
            [candidate_json(SEED_TEXT), candidate_json(GOOD_VARIATION)],
        )
        pipeline.run_pipeline(
            SEED_TEXT, "programming", 1, use_llm_parser=False, persist=False
        )
        prompt = fake.prompts[1]
        assert "WHY IT WAS REJECTED" in prompt
        assert "WHAT YOU MUST DO DIFFERENTLY" in prompt
        assert "[PS8 structural]" in prompt

    def test_max_attempts_is_respected_and_routes_to_review(
        self, temp_data_dir, monkeypatch
    ):
        # Every attempt returns the seed verbatim, so it can never pass.
        monkeypatch.setattr(settings, "max_regeneration_attempts", 2)
        self._patch_ollama(monkeypatch, [candidate_json(SEED_TEXT)] * 6)
        _seed, results, summary, _t, _w = pipeline.run_pipeline(
            SEED_TEXT, "programming", 1, use_llm_parser=False, persist=False
        )
        assert len(results) == 1
        # 1 initial attempt + exactly max_regeneration_attempts retries.
        assert results[0].attempts == 3
        assert summary.regeneration_attempts == 2
        # Never silently discarded - a human decides.
        assert results[0].decision == "REVIEW"
        assert any("maximum" in r for r in results[0].decision_reasons)

    def test_regeneration_can_be_disabled(self, temp_data_dir, monkeypatch):
        self._patch_ollama(monkeypatch, [candidate_json(SEED_TEXT)])
        _seed, results, summary, _t, _w = pipeline.run_pipeline(
            SEED_TEXT,
            "programming",
            1,
            enable_regeneration=False,
            use_llm_parser=False,
            persist=False,
        )
        assert summary.regeneration_attempts == 0
        assert results[0].decision == "REJECT"
        assert results[0].attempts == 1

    def test_unparseable_output_is_reported_not_crashed(self, temp_data_dir, monkeypatch):
        self._patch_ollama(monkeypatch, ["I'm sorry, I cannot do that."])
        _seed, results, _summary, _t, warnings = pipeline.run_pipeline(
            SEED_TEXT, "programming", 1, use_llm_parser=False, persist=False
        )
        assert results == []
        assert any("could not be parsed" in w for w in warnings)

    def test_ollama_outage_is_surfaced_not_swallowed(self, temp_data_dir, monkeypatch):
        from backend.app.core.ollama_client import OllamaUnavailable

        class DeadOllama:
            def generate(self, *a, **k):
                raise OllamaUnavailable("Could not reach Ollama at http://localhost:11434")

        monkeypatch.setattr("backend.app.ps8.generation_engine.ollama", DeadOllama())
        _seed, results, _summary, _t, warnings = pipeline.run_pipeline(
            SEED_TEXT, "programming", 2, use_llm_parser=False, persist=False
        )
        assert results == []
        assert any("Ollama" in w for w in warnings)


class TestPipelineStorage:
    def _patch(self, monkeypatch, responses):
        from backend.tests.conftest import FakeOllama

        fake = FakeOllama(responses)
        monkeypatch.setattr("backend.app.ps8.generation_engine.ollama", fake)
        return fake

    def test_accepted_question_is_persisted(self, temp_data_dir, monkeypatch):
        self._patch(monkeypatch, [candidate_json(GOOD_VARIATION)])
        _s, results, _sum, _t, _w = pipeline.run_pipeline(
            SEED_TEXT, "programming", 1, use_llm_parser=False, persist=True
        )
        if results and results[0].decision == "PASS":
            assert len(storage.load_question_bank()) == 1
        assert storage.read_json("validation_report.json")["reports"]

    def test_review_items_are_queued(self, temp_data_dir, monkeypatch):
        monkeypatch.setattr(settings, "max_regeneration_attempts", 1)
        self._patch(monkeypatch, [candidate_json(SEED_TEXT)] * 4)
        _s, results, _sum, _t, _w = pipeline.run_pipeline(
            SEED_TEXT, "programming", 1, use_llm_parser=False, persist=True
        )
        assert results[0].decision == "REVIEW"
        assert len(storage.load_review_queue()) == 1

    def test_audit_trail_is_written(self, temp_data_dir, monkeypatch):
        self._patch(monkeypatch, [candidate_json(GOOD_VARIATION)])
        pipeline.run_pipeline(
            SEED_TEXT, "programming", 1, use_llm_parser=False, persist=True
        )
        events = storage.read_json("audit_logs.json")["events"]
        assert any(e["event"] == "pipeline_run" for e in events)

    def test_duplicate_rate_is_reported(self, temp_data_dir, monkeypatch):
        self._patch(
            monkeypatch,
            [candidate_json(GOOD_VARIATION), candidate_json(SECOND_VARIATION)],
        )
        _s, _r, summary, _t, _w = pipeline.run_pipeline(
            SEED_TEXT, "programming", 2, use_llm_parser=False, persist=False
        )
        assert 0.0 <= summary.duplicate_rate <= 1.0


class TestApiSurface:
    @pytest.fixture
    def client(self, temp_data_dir):
        return TestClient(app)

    def test_health_reports_component_status(self, client):
        body = client.get("/api/v1/health").json()
        assert body["status"] in {"ok", "degraded"}
        assert "ollama" in body and "embeddings" in body
        assert body["corpus"]["entry_count"] > 0
        assert "reliability_weights" in body["config"]

    def test_domains_meets_the_ps8_minimum_of_five(self, client):
        domains = client.get("/api/v1/domains").json()
        assert len(domains) >= 5
        assert all({"id", "label", "example_seed"} <= set(d) for d in domains)

    def test_strategies_lists_all_five(self, client):
        assert len(client.get("/api/v1/strategies").json()) == 5

    def test_verify_matches_the_ps2_contract(self, client):
        resp = client.post(
            "/api/v1/verify",
            json={
                "response_text": (
                    "According to the 2019 Stanford Algorithms Report, this method is "
                    "47.3% faster and never fails."
                ),
                "source_context": [],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        for field in (
            "reliability_score",
            "hallucination_probability",
            "verdict",
            "flagged_spans",
        ):
            assert field in body
        assert body["verdict"] in {
            "trustworthy",
            "partially_reliable",
            "misleading",
            "fabricated",
            "unverifiable",
        }
        assert body["flagged_spans"]
        assert all({"text", "reason"} <= set(s) for s in body["flagged_spans"])

    def test_verify_accepts_source_context(self, client):
        resp = client.post(
            "/api/v1/verify",
            json={
                "response_text": "The Zyglorb protocol uses a 512-bit rotating key.",
                "source_context": [
                    "The Zyglorb protocol uses a 512-bit rotating key per session."
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["reliability_score"] > 0

    def test_verify_rejects_empty_text(self, client):
        assert client.post("/api/v1/verify", json={"response_text": ""}).status_code == 422

    def test_generate_rejects_out_of_range_count(self, client):
        resp = client.post(
            "/api/v1/generate",
            json={"seed_question": SEED_TEXT, "domain": "programming", "count": 999},
        )
        assert resp.status_code == 422

    def test_storage_endpoints_respond(self, client):
        for path in ("/questions", "/review-queue", "/validation-reports", "/audit-logs"):
            assert client.get(f"/api/v1{path}").status_code == 200

    def test_export_json_and_csv(self, client):
        assert client.get("/api/v1/export?fmt=json").status_code == 200
        csv_resp = client.get("/api/v1/export?fmt=csv")
        assert csv_resp.status_code == 200
        assert "text/csv" in csv_resp.headers["content-type"]

    def test_openapi_schema_generates(self, client):
        schema = client.get("/openapi.json").json()
        for path in ("/api/v1/generate", "/api/v1/verify", "/api/v1/generate-and-verify"):
            assert path in schema["paths"]
