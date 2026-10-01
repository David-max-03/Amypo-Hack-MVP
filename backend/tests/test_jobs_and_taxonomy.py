"""Backend-owned jobs, automatic PS2 on every candidate, the shared taxonomy, Expert."""

from __future__ import annotations

import shutil
import time

import pytest
from fastapi.testclient import TestClient

from backend.app import taxonomy
from backend.app.core import storage
from backend.app.main import app
from backend.tests.conftest import REPO_ROOT, FakeOllama, candidate_json

SEED = "Write a function to reverse a singly linked list."
GOOD = (
    "A music app stores its play queue as a singly linked list of track nodes. "
    "Implement a routine that reverses the queue so the last track plays first, "
    "rewiring the existing nodes rather than allocating a new queue."
)


def _wait(client, job_id, timeout=180.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish: {job}")


@pytest.fixture(scope="module", autouse=True)
def _warm_embeddings():
    # Load MiniLM once, outside any timed assertion: its first load can stall on
    # Hugging Face network checks even though the weights are cached locally.
    from backend.app.core.embeddings import embeddings

    embeddings.warm_up()


@pytest.fixture
def client(temp_data_dir, monkeypatch):
    from backend.app.ps8 import seed_parser

    shutil.copytree(REPO_ROOT / "data" / "demo", temp_data_dir / "demo")
    monkeypatch.setattr(
        "backend.app.pipeline.seed_parser.parse_seed",
        lambda text, domain, use_llm=True: seed_parser.heuristic_parse(text, domain),
    )
    yield TestClient(app)
    # A job thread must never outlive the test: once the fixtures below are torn
    # down it would write into the REAL data directory with the REAL model.
    from backend.app.jobs import jobs

    assert jobs.wait_idle(timeout=240), "a background job was still running at teardown"


def _script(monkeypatch, responses, delay=0.0):
    class Slow(FakeOllama):
        def generate(self, prompt, **kw):
            time.sleep(delay)
            return super().generate(prompt, **kw)

    fake = Slow(responses)
    monkeypatch.setattr("backend.app.ps8.generation_engine.ollama", fake)
    return fake


class TestBackgroundJobs:
    def test_start_returns_immediately_and_the_job_finishes_on_its_own(self, client, monkeypatch):
        _script(monkeypatch, [candidate_json(GOOD)], delay=0.4)
        t = time.monotonic()
        started = client.post("/api/v1/jobs", json={"seed_question": SEED, "count": 1, "persist": False})
        assert started.status_code == 202
        assert time.monotonic() - t < 0.35  # did not wait for the model
        assert started.json()["status"] in ("queued", "running")
        job = _wait(client, started.json()["job_id"])
        assert job["status"] == "completed"
        assert job["requested_count"] == 1 and job["generated_count"] == 1
        assert len(job["results"]) == 1 and job["summary"]["generated"] == 1
        assert job["started_at"] and job["completed_at"]
        for key in ("job_id", "seed", "current_stage", "accepted_count", "errors"):
            assert key in job

    def test_job_results_are_persisted_like_a_normal_run(self, client, monkeypatch):
        _script(monkeypatch, [candidate_json(GOOD)])
        job = _wait(client, client.post("/api/v1/jobs", json={"seed_question": SEED, "count": 1}).json()["job_id"])
        stored = storage.load_question_bank() + storage.load_review_queue()
        assert [r["id"] for r in stored] == [job["results"][0]["candidate"]["id"]]

    def test_list_omits_results_and_unknown_job_is_404(self, client, monkeypatch):
        _script(monkeypatch, [candidate_json(GOOD)])
        job_id = client.post("/api/v1/jobs", json={"seed_question": SEED, "count": 1, "persist": False}).json()["job_id"]
        _wait(client, job_id)
        listed = client.get("/api/v1/jobs").json()["jobs"]
        assert listed[0]["job_id"] == job_id and "results" not in listed[0]
        assert client.get("/api/v1/jobs/job_nope").status_code == 404

    def test_model_outage_ends_the_job_as_failed_with_the_error(self, client, monkeypatch):
        from backend.app.core.ollama_client import OllamaUnavailable

        class Dead:
            def generate(self, *a, **k):
                raise OllamaUnavailable("Could not reach Ollama")

        monkeypatch.setattr("backend.app.ps8.generation_engine.ollama", Dead())
        job = _wait(client, client.post("/api/v1/jobs", json={"seed_question": SEED, "count": 1, "persist": False}).json()["job_id"])
        assert job["status"] == "failed"
        assert any("Ollama" in e for e in job["errors"])

    def test_demo_job_keeps_demo_behaviour_and_writes_nothing(self, client, monkeypatch):
        before = (len(storage.load_question_bank()), len(storage.load_review_queue()))
        job = _wait(client, client.post("/api/v1/jobs/demo").json()["job_id"])
        assert job["status"] == "completed" and job["demo"] is True and "DEMO" in job["demo_label"]
        item = job["results"][0]
        assert item["regeneration_history"][0]["decision"] == "REJECT"
        assert item["decision"] == "PASS" and item["attempts"] == 2
        assert (len(storage.load_question_bank()), len(storage.load_review_queue())) == before


class TestAutomaticPs2:
    def test_ps2_runs_even_when_ps8_fails(self, client, monkeypatch):
        # A paraphrase of the seed fails PS8; regeneration off so we see that attempt.
        _script(monkeypatch, [candidate_json(SEED)])
        job = _wait(client, client.post("/api/v1/jobs", json={
            "seed_question": SEED, "count": 1, "persist": False, "enable_regeneration": False,
        }).json()["job_id"])
        item = job["results"][0]
        assert item["structural_validation"]["passed"] is False
        assert item["decision"] == "REJECT"  # decision logic unchanged
        rv = item["reliability_verification"]
        assert rv is not None and isinstance(rv["reliability_score"], float) and rv["verdict"]


class TestTaxonomy:
    REQUIRED = [
        "Algorithms", "Data Structures", "Web Development", "Database", "Operating Systems",
        "Computer Networks", "Computer Architecture", "OOP", "Software Engineering",
        "AI / Machine Learning", "Cloud Computing", "Cybersecurity", "Programming Languages",
        "System Design",
    ]

    def test_all_required_areas_and_difficulties(self, client):
        body = client.get("/api/v1/taxonomy").json()
        labels = [a["label"] for a in body["subject_areas"]]
        for name in self.REQUIRED:
            assert name in labels
        assert [d["label"] for d in body["difficulties"]] == ["Easy", "Medium", "Hard", "Expert"]

    def test_every_area_maps_to_a_supported_pipeline_domain(self):
        from backend.app.ps8 import domains

        for area in taxonomy.subject_areas():
            assert domains.is_supported(area["pipeline_domain"])
        cs = [a for a in taxonomy.subject_areas() if a["group"] == taxonomy.CS_GROUP]
        assert {a["pipeline_domain"] for a in cs} == {"programming"}

    def test_subject_area_is_recorded_and_unknown_area_rejected(self, client, monkeypatch):
        _script(monkeypatch, [candidate_json(GOOD)])
        job = _wait(client, client.post("/api/v1/jobs", json={
            "seed_question": SEED, "subject_area": "data_structures", "count": 1,
        }).json()["job_id"])
        assert job["domain"] == "programming" and job["subject_area"] == "data_structures"
        assert job["results"][0]["subject_area"] == "data_structures"
        stored = (storage.load_question_bank() + storage.load_review_queue())[0]
        assert stored["subject_area"] == "data_structures"
        report = storage.read_json("validation_report.json")["reports"][-1]
        assert report["subject_area"] == "data_structures" and report["difficulty"]
        bad = client.post("/api/v1/jobs", json={"seed_question": SEED, "subject_area": "astrology"})
        assert bad.status_code == 422


class TestExpertDifficulty:
    def test_expert_is_accepted_as_a_target_and_reaches_the_prompt(self, client, monkeypatch):
        fake = _script(monkeypatch, [candidate_json(GOOD, difficulty="expert")])
        job = _wait(client, client.post("/api/v1/jobs", json={
            "seed_question": SEED, "count": 1, "persist": False, "difficulty_shift": "expert",
        }).json()["job_id"])
        assert job["status"] == "completed"
        assert "'expert'" in fake.prompts[0] and "easy | medium | hard | expert" in fake.prompts[0]

    def test_prompt_is_unchanged_when_expert_is_not_requested(self, client, monkeypatch):
        fake = _script(monkeypatch, [candidate_json(GOOD)])
        _wait(client, client.post("/api/v1/jobs", json={"seed_question": SEED, "count": 1, "persist": False}).json()["job_id"])
        assert '"easy | medium | hard"' in fake.prompts[0] and "expert" not in fake.prompts[0]

    def test_estimator_never_emits_expert(self):
        from backend.app.ps8.seed_parser import estimate_difficulty

        text = ("Design an optimal, provably correct O(n log n) algorithm with amortised analysis, "
                "handling concurrency, edge cases and a formal proof across distributed nodes " * 3)
        assert estimate_difficulty(text)[0] == "hard"
