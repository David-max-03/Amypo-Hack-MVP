"""Shared fixtures.

The unit suite never touches Ollama: generation is faked so the tests are fast and
deterministic. Tests that genuinely need the model are marked `integration` and skip
themselves when Ollama is not reachable.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from backend.app.config import settings
from backend.app.core import storage
from backend.app.ps2.source_verification import corpus
from backend.app.ps8 import seed_parser, variation_planner
from backend.app.schemas import Candidate, SeedMetadata, VariationPlanItem

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def temp_data_dir(monkeypatch):
    """Point storage at a throwaway directory seeded with the real corpus."""
    tmp = Path(tempfile.mkdtemp(prefix="amypo-test-"))
    shutil.copy(
        REPO_ROOT / "data" / "reference_corpus.json", tmp / "reference_corpus.json"
    )
    monkeypatch.setattr(settings, "data_dir", tmp)
    corpus.reset()
    storage.ensure_data_files()
    yield tmp
    corpus.reset()
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def seed() -> SeedMetadata:
    """A deterministic seed - parsed heuristically, so no model is involved."""
    return seed_parser.heuristic_parse(
        "Write a function to reverse a singly linked list.", "programming"
    )


@pytest.fixture
def plan(seed) -> list[VariationPlanItem]:
    return variation_planner.plan_variations(seed, 5)


def make_candidate(
    question: str,
    *,
    answer_key: str = "Use three pointers and rewire each next pointer in one pass.",
    difficulty: str = "medium",
    difficulty_score: float = 0.55,
    domain: str = "programming",
    strategy: str = "scenario",
    **kwargs,
) -> Candidate:
    """Build a Candidate directly, bypassing the model."""
    defaults = dict(
        id="q_test",
        question=question,
        answer_key=answer_key,
        domain=domain,
        topic="Singly Linked List",
        difficulty=difficulty,
        difficulty_score=difficulty_score,
        question_type="coding",
        learning_objective="The learner should be able to implement singly linked list.",
        variation_strategy=strategy,
        strategy_label=strategy.title(),
    )
    defaults.update(kwargs)
    return Candidate(**defaults)


@pytest.fixture
def candidate_factory():
    return make_candidate


class FakeOllama:
    """Returns scripted responses in order, recording every prompt it received."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []
        self.calls = 0

    def generate(self, prompt: str, **kwargs) -> str:
        self.prompts.append(prompt)
        self.calls += 1
        if not self.responses:
            raise AssertionError("FakeOllama ran out of scripted responses")
        return self.responses.pop(0)

    def status(self):  # pragma: no cover - only used by health checks
        from backend.app.core.ollama_client import OllamaStatus

        return OllamaStatus(True, "fake", "fake-model", True, ["fake-model"], "ok")


@pytest.fixture
def fake_ollama():
    return FakeOllama


def candidate_json(question: str, answer: str = "A correct and complete answer key.", **extra) -> str:
    payload = {
        "question": question,
        "answer_key": answer,
        "domain": "programming",
        "topic": "Linked Lists",
        "difficulty": "medium",
        "question_type": "coding",
        "learning_objective": "The learner should be able to implement linked list reversal.",
        "test_cases": [],
    }
    payload.update(extra)
    return json.dumps(payload)


@pytest.fixture
def ollama_available() -> bool:
    from backend.app.core.ollama_client import ollama

    status = ollama.status()
    return status.reachable and status.model_available


requires_ollama = pytest.mark.skipif(
    not __import__("backend.app.core.ollama_client", fromlist=["ollama"])
    .ollama.status()
    .model_available,
    reason="Ollama is not running or the configured model is not pulled",
)
