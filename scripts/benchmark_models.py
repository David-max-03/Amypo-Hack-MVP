"""Benchmark local generation models through the real integrated pipeline.

Every model runs the identical pipeline (same seed, count, domain, temperature,
top_p, token budget, PS8 rules and PS2 engine). Only the Ollama model name changes.
Nothing is persisted: `persist=False`, so the question bank and review queue are
untouched.

Usage (from the repo root, with Ollama running and both models pulled):

      .venv/bin/python scripts/benchmark_models.py \
        --models qwen2.5-coder:7b mistral:7b --count 5 --runs 1 --concurrency 2

What it measures (all wall-clock, time.perf_counter):
  * per model call: latency, and whether the raw output was malformed (no JSON
    object recoverable by the pipeline's own tolerant parser)
  * per pipeline run: the pipeline's own Stopwatch stages (seed parsing, generation,
    regeneration, PS8 structural validation, PS2 verification, total)
  * per candidate: attempts, decision, PS8 pass, PS2 score and verdict
  * concurrent throughput: `--concurrency` identical pipelines in parallel threads,
    reported as decided candidates per minute of wall time

Sampling: Ollama is given a fixed `seed` option (default 42) so both models see a
reproducible sampler; production traffic does not set one. Everything else is
taken from app settings, unchanged.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402

from app.config import settings  # noqa: E402
from app.core.ollama_client import OllamaClient, OllamaUnavailable  # noqa: E402
from app.pipeline import run_pipeline  # noqa: E402
from app.ps8.candidate_builder import extract_json_object  # noqa: E402

DEFAULT_SEED = "Write a function to reverse a singly linked list."


class TimedClient(OllamaClient):
    """The production OllamaClient payload, plus a fixed sampler seed and per-call timing."""

    def __init__(self, model: str, sampler_seed: int) -> None:
        super().__init__(model=model)
        self.sampler_seed = sampler_seed
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def generate(self, prompt, *, system=None, temperature=None, timeout_s=None,
                 json_mode=True, max_tokens=None) -> str:
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": settings.generation_temperature if temperature is None else temperature,
                "top_p": settings.generation_top_p,
                "num_predict": max_tokens or settings.max_generation_tokens,
                "seed": self.sampler_seed,
            },
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"
        start = time.perf_counter()
        error = None
        text = ""
        body: dict = {}
        try:
            with httpx.Client(timeout=timeout_s or settings.ollama_timeout_s) as client:
                resp = client.post(f"{self.host}/api/generate", json=payload)
                resp.raise_for_status()
                body = resp.json()
                text = body.get("response", "")
        except Exception as exc:  # recorded, then surfaced the way production does
            error = f"{type(exc).__name__}: {exc}"
        elapsed = (time.perf_counter() - start) * 1000.0
        obj, _ = extract_json_object(text) if text else (None, [])
        with self._lock:
            self.calls.append({
                "ms": round(elapsed, 1),
                "temperature": payload["options"]["temperature"],
                "malformed": obj is None,
                "error": error,
                "eval_count": body.get("eval_count"),
            })
        if error:
            raise OllamaUnavailable(error)
        return text


def one_pipeline(client: TimedClient, args) -> dict:
    start = time.perf_counter()
    seed, results, summary, timings, warnings = run_pipeline(
        args.seed, "programming", args.count,
        enable_regeneration=True, verify=True, persist=False,
        use_llm_parser=False, client=client, subject_area="data_structures",
    )
    wall = (time.perf_counter() - start) * 1000.0
    cands = []
    for r in results:
        sv, rv = r.structural_validation, r.reliability_verification
        cands.append({
            "decision": r.decision,
            "attempts": r.attempts,
            "ps8_passed": bool(sv and sv.passed),
            "ps2_score": rv.reliability_score if rv else None,
            "ps2_verdict": rv.verdict if rv else None,
            "question": r.candidate.question[:160],
        })
    return {"wall_ms": round(wall, 1), "timings_ms": timings, "warnings": warnings,
            "summary": summary.model_dump(), "candidates": cands}


def bench_model(model: str, args) -> dict:
    client = TimedClient(model, args.sampler_seed)
    if not client.status().model_available:
        return {"model": model, "error": f"model {model!r} not available in Ollama"}
    # Load the model into memory so the first timed call is not a cold load.
    warm = time.perf_counter()
    client.generate('Reply with {"ok": true}', max_tokens=8)
    warm_ms = round((time.perf_counter() - warm) * 1000.0, 1)
    client.calls.clear()

    sequential = [one_pipeline(client, args) for _ in range(args.runs)]
    seq_calls = list(client.calls)

    concurrent = None
    if args.concurrency > 1:
        client.calls.clear()
        out: list = [None] * args.concurrency

        def worker(i: int) -> None:
            out[i] = one_pipeline(client, args)

        start = time.perf_counter()
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(args.concurrency)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall = (time.perf_counter() - start) * 1000.0
        decided = sum(len(r["candidates"]) for r in out if r)
        concurrent = {
            "pipelines": args.concurrency,
            "wall_ms": round(wall, 1),
            "decided_candidates": decided,
            "candidates_per_min": round(decided / (wall / 60000.0), 2) if wall else None,
            "model_calls": len(client.calls),
            "mean_call_ms": round(statistics.mean(c["ms"] for c in client.calls), 1) if client.calls else None,
            "runs": out,
        }

    seq_metrics = metrics(sequential, seq_calls, args)
    seq_decided = seq_metrics["decided"]
    seq_wall = seq_metrics["total_ms"]
    seq_metrics["sequential_candidates_per_min"] = (
        round(seq_decided / (seq_wall / 60000.0), 2) if seq_wall else None
    )
    return {"model": model, "warmup_ms": warm_ms, "sequential": sequential,
            "sequential_calls": seq_calls, "concurrent": concurrent, "metrics": seq_metrics}


def metrics(runs: list[dict], calls: list[dict], args) -> dict:
    cands = [c for r in runs for c in r["candidates"]]
    requested = args.count * len(runs)
    stage = lambda k: round(sum(r["timings_ms"].get(k, 0.0) for r in runs), 1)  # noqa: E731
    total = sum(r["wall_ms"] for r in runs)
    # Generation calls use generation_temperature; regeneration calls use the lower one.
    gen_calls = [c for c in calls if c["temperature"] == settings.generation_temperature]
    regen_calls = [c for c in calls if c["temperature"] != settings.generation_temperature]
    scores = [c["ps2_score"] for c in cands if c["ps2_score"] is not None]
    return {
        "requested": requested,
        "decided": len(cands),
        "valid_rate": round(len(cands) / requested, 3) if requested else None,
        "decisions": dict(Counter(c["decision"] for c in cands)),
        "ps8_pass_rate": round(sum(c["ps8_passed"] for c in cands) / len(cands), 3) if cands else None,
        "ps2_verdicts": dict(Counter(c["ps2_verdict"] for c in cands)),
        "ps2_score_mean": round(statistics.mean(scores), 3) if scores else None,
        "ps2_score_min": round(min(scores), 3) if scores else None,
        "ps2_score_max": round(max(scores), 3) if scores else None,
        "regenerated_candidates": sum(c["attempts"] > 1 for c in cands),
        "regeneration_rate": round(sum(c["attempts"] > 1 for c in cands) / len(cands), 3) if cands else None,
        "model_calls": len(calls),
        "malformed_calls": sum(c["malformed"] for c in calls),
        "malformed_rate": round(sum(c["malformed"] for c in calls) / len(calls), 3) if calls else None,
        "call_errors": sum(bool(c["error"]) for c in calls),
        "mean_generation_call_ms": round(statistics.mean(c["ms"] for c in gen_calls), 1) if gen_calls else None,
        "mean_regeneration_call_ms": round(statistics.mean(c["ms"] for c in regen_calls), 1) if regen_calls else None,
        "stage_ms": {k: stage(k) for k in (
            "ps8.seed_parsing", "ps8.generation", "ps8.regeneration",
            "ps8.structural_validation", "ps2.verification",
        )},
        "total_ms": round(total, 1),
        "avg_ms_per_decided_candidate": round(total / len(cands), 1) if cands else None,
        "warnings": [w for r in runs for w in r["warnings"]],
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", nargs="+", default=["qwen2.5-coder:7b", "mistral:7b"])
    p.add_argument("--seed", default=DEFAULT_SEED)
    p.add_argument("--count", type=int, default=5)
    p.add_argument("--runs", type=int, default=1, help="sequential pipeline runs per model")
    p.add_argument("--concurrency", type=int, default=0, help="parallel pipelines for the throughput test (0 = skip)")
    p.add_argument("--sampler-seed", type=int, default=42)
    p.add_argument("--out", default=str(ROOT / "docs" / "benchmark"))
    args = p.parse_args()

    # Load MiniLM once so its start-up is not charged to the first model benchmarked.
    from app.ps2 import engine as ps2_engine
    ps2_engine.verify_text("Warm-up sentence for the embedding model.")

    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "settings": {
            "seed_question": args.seed, "count": args.count, "runs": args.runs,
            "concurrency": args.concurrency, "sampler_seed": args.sampler_seed,
            "generation_temperature": settings.generation_temperature,
            "regeneration_temperature": settings.regeneration_temperature,
            "top_p": settings.generation_top_p,
            "max_generation_tokens": settings.max_generation_tokens,
            "max_regeneration_attempts": settings.max_regeneration_attempts,
            "ollama_host": settings.ollama_host,
        },
        "models": [],
    }
    for model in args.models:
        print(f"== {model}", flush=True)
        res = bench_model(model, args)
        report["models"].append(res)
        print(json.dumps(res.get("metrics") or res, indent=2), flush=True)
        if res.get("concurrent"):
            c = res["concurrent"]
            print(f"   concurrent x{c['pipelines']}: {c['decided_candidates']} decided in "
                  f"{c['wall_ms'] / 1000:.1f}s = {c['candidates_per_min']}/min", flush=True)
    report["finished_at"] = datetime.now(timezone.utc).isoformat()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out / f"benchmark_{stamp}.json"
    path.write_text(json.dumps(report, indent=2))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
