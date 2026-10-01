"""Demo Mode: a deterministic run of the REAL pipeline.

Generation is the one nondeterministic step - a local LLM will not produce the same
reject-then-pass sequence on cue. Demo Mode replaces only that step with a scripted
replay of two candidate outputs from `data/demo/demo_scenario.json`. Everything after
the model call is production code, unchanged: JSON parsing, PS8 structural
validation, PS2 reliability verification, the decision engine and the feedback-driven
regeneration loop. No score, verdict or decision is stored or hard-coded - they are
all computed live, exactly as in a normal run.

Demo runs are never persisted, so they cannot enter the question bank, the review
queue or the duplicate-detection memory, and they are labelled DEMO end to end.
"""

from __future__ import annotations

import json
from typing import Any

from .config import settings
from .pipeline import ProgressCallback, run_pipeline

DEMO_LABEL = "DEMO — scripted candidates, real validation. Not a measured benchmark result."


def load_scenario() -> dict[str, Any]:
    with (settings.data_dir / "demo" / "demo_scenario.json").open(encoding="utf-8") as fh:
        return json.load(fh)


class ScriptedReplay:
    """Stands in for the Ollama client: returns the scenario's outputs in order.

    It records every prompt it receives, so a test can prove the regeneration prompt
    really carried the rejection feedback.
    """

    def __init__(self, outputs: list[str]) -> None:
        self._outputs = list(outputs)
        self.prompts: list[str] = []

    def generate(self, prompt: str, **_: Any) -> str:
        self.prompts.append(prompt)
        if not self._outputs:
            # More model calls than the scenario scripts: surface it, never invent output.
            return ""
        return self._outputs.pop(0)


def run_demo(progress: ProgressCallback | None = None, replay: ScriptedReplay | None = None):
    """Run the scenario through the real pipeline. Returns run_pipeline's tuple + scenario."""
    scenario = load_scenario()
    replay = replay or ScriptedReplay(
        [json.dumps(c["output"]) for c in scenario["candidate_outputs"]]
    )
    seed, results, summary, timings, warnings = run_pipeline(
        scenario["seed_question"],
        scenario["domain"],
        1,
        enable_regeneration=True,
        verify=True,
        persist=False,          # never enters the bank, review queue or duplicate memory
        use_llm_parser=False,   # deterministic heuristic seed parse
        progress=progress,
        client=replay,
    )
    return seed, results, summary, timings, warnings, scenario
