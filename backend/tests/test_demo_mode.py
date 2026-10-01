"""Demo Mode: scripted candidates through the REAL pipeline, labelled and never persisted."""

from __future__ import annotations

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from backend.app import demo
from backend.app.core import storage
from backend.app.main import app
from backend.tests.conftest import REPO_ROOT


@pytest.fixture
def demo_data(temp_data_dir):
    shutil.copytree(REPO_ROOT / "data" / "demo", temp_data_dir / "demo")
    return temp_data_dir


def _stores_snapshot():
    return (
        len(storage.load_question_bank()),
        len(storage.load_review_queue()),
        len(storage.read_json("validation_report.json").get("reports", [])),
        len(storage.read_json("audit_logs.json").get("events", [])),
    )


class TestDemoScenarioFile:
    def test_scenario_holds_only_candidate_text_never_results(self):
        scenario = json.loads((REPO_ROOT / "data" / "demo" / "demo_scenario.json").read_text())
        assert "DEMO" in scenario["label"]
        for c in scenario["candidate_outputs"]:
            # Nothing that the validators compute may be pre-stored in the scenario.
            assert set(c["output"]) <= {"question", "answer_key", "difficulty", "test_cases"}


class TestDemoRun:
    def test_reject_then_regenerate_then_pass(self, demo_data):
        body = TestClient(app).post("/api/v1/demo/run", json={}).json()
        assert body["demo"] is True and "DEMO" in body["demo_label"]
        item = body["results"][0]

        first = item["regeneration_history"][0]
        assert first["attempt"] == 1 and first["decision"] == "REJECT"
        # Attempt 1 went through BOTH gates and was rejected by PS2, not by a script.
        assert first["structural_passed"] is True
        assert first["verdict"] in {"misleading", "fabricated"}
        assert any(
            "Recursive linked list reversal space cost" in s["reason"] for s in first["flagged_spans"]
        )

        assert item["decision"] == "PASS" and item["attempts"] == 2
        assert item["structural_validation"]["passed"] is True
        final = item["reliability_verification"]
        assert final["verdict"] == "trustworthy"
        assert final["reliability_score"] > first["reliability_score"]
        assert body["summary"]["regeneration_attempts"] == 1

    def test_regeneration_prompt_carries_the_rejection_feedback(self, demo_data):
        replay = demo.ScriptedReplay(
            [json.dumps(c["output"]) for c in demo.load_scenario()["candidate_outputs"]]
        )
        demo.run_demo(replay=replay)
        assert len(replay.prompts) == 2
        assert "REGENERATION" in replay.prompts[1]
        assert "Recursive linked list reversal space cost" in replay.prompts[1]

    def test_demo_is_deterministic(self, demo_data):
        client = TestClient(app)
        a = client.post("/api/v1/demo/run").json()["results"][0]
        b = client.post("/api/v1/demo/run").json()["results"][0]
        for key in ("decision", "attempts"):
            assert a[key] == b[key]
        assert a["reliability_verification"]["reliability_score"] == \
            b["reliability_verification"]["reliability_score"]
        assert a["regeneration_history"][0]["reliability_score"] == \
            b["regeneration_history"][0]["reliability_score"]

    def test_demo_never_writes_to_any_store(self, demo_data):
        before = _stores_snapshot()
        TestClient(app).post("/api/v1/demo/run", json={"job_id": "demo-test"})
        assert _stores_snapshot() == before

    def test_demo_reports_progress_for_a_job(self, demo_data):
        client = TestClient(app)
        client.post("/api/v1/demo/run", json={"job_id": "demo-progress"})
        job = client.get("/api/v1/progress/demo-progress").json()
        assert job["stage"] == "complete"
        assert job["decisions"] == [{"variation": 1, "decision": "PASS", "attempts": 2}]

    def test_demo_uses_no_real_model(self, demo_data, monkeypatch):
        """If Demo Mode ever reached Ollama, this would raise."""
        class Boom:
            def generate(self, *a, **k):
                raise AssertionError("Demo Mode must not call the real model")

        monkeypatch.setattr("backend.app.ps8.generation_engine.ollama", Boom())
        assert TestClient(app).post("/api/v1/demo/run").status_code == 200


def test_normal_pipeline_response_is_not_marked_demo(temp_data_dir, monkeypatch):
    from backend.app.ps8 import seed_parser
    from backend.tests.conftest import FakeOllama, candidate_json

    monkeypatch.setattr(
        "backend.app.pipeline.seed_parser.parse_seed",
        lambda text, domain, use_llm=True: seed_parser.heuristic_parse(text, domain),
    )
    monkeypatch.setattr(
        "backend.app.ps8.generation_engine.ollama",
        FakeOllama([candidate_json(
            "A music app stores its play queue as a singly linked list of track nodes. "
            "Implement a routine that reverses the queue so the last track plays first, "
            "rewiring the existing nodes rather than allocating a new queue."
        )]),
    )
    body = TestClient(app).post(
        "/api/v1/generate-and-verify",
        json={"seed_question": "Write a function to reverse a singly linked list.",
              "domain": "programming", "count": 1, "persist": False},
    ).json()
    assert body["demo"] is False and body["demo_label"] is None
