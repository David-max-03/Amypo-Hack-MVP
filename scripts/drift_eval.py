"""Semantic-drift evaluation: real generations for representative seeds across domains.

Runs the real integrated pipeline (real model, real PS8 and PS2, nothing persisted)
for one seed per domain and saves every candidate - including each rejected attempt -
with the PS8 checks and reasons, so drift can be inspected and compared between
versions of the code.

    .venv/bin/python scripts/drift_eval.py --label baseline --count 5

The script only uses the public `run_pipeline` API, so the same file measures the
code before and after a change.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import taxonomy  # noqa: E402
from app.config import settings  # noqa: E402
from app.pipeline import run_pipeline  # noqa: E402

# One representative seed per domain. Deliberately varied in task type: code,
# query, markup, explanation, calculation.
SEEDS: list[tuple[str, str, str]] = [
    ("programming", "programming", "Write a function to check whether a number is prime."),
    ("algorithms", "algorithms", "Implement binary search on a sorted array of integers."),
    ("data_structures", "data_structures", "Implement a stack that supports push, pop and retrieving the minimum element."),
    ("database", "databases", "Write a SQL query to find duplicate email addresses in a users table."),
    ("operating_systems", "operating_systems", "Explain how round-robin CPU scheduling decides which process runs next."),
    ("computer_networks", "computer_networks", "Explain how TCP congestion control uses slow start and congestion avoidance."),
    ("ai_ml", "ai_ml", "Explain how the k-nearest neighbours algorithm classifies a new data point."),
    ("web_development", "web_development", "Write an HTML form that collects a user's name and email address."),
    ("software_engineering", "software_engineering", "Explain the difference between unit testing and integration testing."),
    ("mathematics", "mathematics", "Find the derivative of f(x) = 3x^2 + 5x - 7."),
]

# A second set, on different topics in the same domains. Kept apart so a change can be
# judged on seeds it was not developed against.
HELDOUT_SEEDS: list[tuple[str, str, str]] = [
    ("programming", "programming", "Write a function to compute the factorial of a non-negative integer."),
    ("algorithms", "algorithms", "Implement merge sort for an array of integers."),
    ("data_structures", "data_structures", "Implement a queue using two stacks."),
    ("database", "databases", "Write a SQL query to find the second highest salary in an employees table."),
    ("operating_systems", "operating_systems", "Explain what a deadlock is and the four conditions required for one to occur."),
    ("computer_networks", "computer_networks", "Explain how DNS resolves a domain name to an IP address."),
    ("ai_ml", "ai_ml", "Explain what overfitting is and how regularisation reduces it."),
    ("web_development", "web_development", "Write a CSS rule that centres a div horizontally and vertically using flexbox."),
    ("software_engineering", "software_engineering", "Explain the difference between a git merge and a git rebase."),
    ("mathematics", "mathematics", "Solve the quadratic equation x^2 - 5x + 6 = 0."),
]

SEED_SETS = {"main": SEEDS, "heldout": HELDOUT_SEEDS}


def _area(area_id: str) -> tuple[str, str]:
    """(subject_area, pipeline_domain) - tolerant of taxonomy id spelling."""
    ids = {a["id"] if isinstance(a, dict) else a.id for a in taxonomy.subject_areas()}
    if area_id not in ids:
        matches = [i for i in ids if i.startswith(area_id.split("_")[0])]
        area_id = matches[0] if matches else "programming"
    return area_id, taxonomy.pipeline_domain_for(area_id) or "programming"


def run_seed(key: str, area_id: str, seed_text: str, count: int, regenerate: bool = True) -> dict:
    area, domain = _area(area_id)
    start = time.perf_counter()
    seed, results, summary, timings, warnings = run_pipeline(
        seed_text, domain, count, enable_regeneration=regenerate, verify=True,
        persist=False, use_llm_parser=True, subject_area=area,
    )
    wall = time.perf_counter() - start
    candidates = []
    for r in results:
        sv, rv = r.structural_validation, r.reliability_verification
        candidates.append({
            "strategy": r.candidate.variation_strategy,
            "method": r.candidate.solution_method,
            "question": r.candidate.question,
            "answer_key": r.candidate.answer_key[:4000],
            "decision": r.decision,
            "attempts": r.attempts,
            "ps8_passed": bool(sv and sv.passed),
            "ps8_reasons": list(sv.reasons) if sv else [],
            "ps8_checks": sv.checks if sv else {},
            "ps2_score": rv.reliability_score if rv else None,
            "ps2_verdict": rv.verdict if rv else None,
            "decision_reasons": r.decision_reasons,
            "rejected_attempts": [
                {"attempt": h["attempt"], "question": h["rejected_question"],
                 "structural_reasons": h["structural_reasons"],
                 "reliability_reasons": h["reliability_reasons"]}
                for h in r.regeneration_history
            ],
        })
    return {
        "key": key, "subject_area": area, "pipeline_domain": domain, "seed": seed_text,
        "seed_metadata": seed.model_dump(), "wall_s": round(wall, 1), "timings_ms": timings,
        "summary": summary.model_dump(), "warnings": warnings, "candidates": candidates,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--label", required=True, help="name for this run, e.g. baseline / contract")
    p.add_argument("--count", type=int, default=5)
    p.add_argument("--only", nargs="*", help="run only these seed keys")
    p.add_argument("--set", choices=sorted(SEED_SETS), default="main", help="which seed set to run")
    p.add_argument("--no-regen", action="store_true", help="first attempts only: measures the prompt, not the retry loop")
    p.add_argument("--out", default=str(ROOT / "docs" / "drift_eval"))
    args = p.parse_args()

    from app.ps2 import engine as ps2_engine
    ps2_engine.verify_text("Warm-up sentence for the embedding model.")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{args.label}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    report = {
        "label": args.label, "started_at": datetime.now(timezone.utc).isoformat(),
        "model": settings.ollama_model, "count": args.count,
        "max_regeneration_attempts": settings.max_regeneration_attempts,
        "regeneration": not args.no_regen, "seed_set": args.set, "seeds": [],
    }
    for key, area, text in SEED_SETS[args.set]:
        if args.only and key not in args.only:
            continue
        print(f"== {key}: {text}", flush=True)
        res = run_seed(key, area, text, args.count, regenerate=not args.no_regen)
        report["seeds"].append(res)
        for c in res["candidates"]:
            print(f"   [{c['decision']:6}] {c['strategy']:14} {str(c['method']):10} a={c['attempts']}  {c['question'][:110]}", flush=True)
        path.write_text(json.dumps(report, indent=2))  # saved after every seed
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(report, indent=2))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
