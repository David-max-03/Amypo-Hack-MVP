"""Backend-owned generation jobs.

A generation run used to live inside one HTTP request that the Generate & Verify
page was waiting on; leaving the page threw away the page's state and its progress
polling. Now the backend owns the job: POST /jobs starts the real pipeline on a
background thread and returns immediately, and GET /jobs/{id} returns its live state
- stage, counts, every candidate decided so far - to whichever page asks, whenever.

State is held in memory for the life of the backend process (bounded to the most
recent jobs). Accepted / review results are still persisted to the JSON stores by
the pipeline itself, exactly as before, so nothing is lost when a job finishes.
"""

from __future__ import annotations

import copy
import logging
import threading
import time
import uuid
from typing import Any

from . import demo
from .core import storage
from .pipeline import run_pipeline

logger = logging.getLogger(__name__)

_MAX_JOBS = 50


def _dump(model: Any) -> Any:
    return model.model_dump(mode="json") if hasattr(model, "model_dump") else model


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ public
    def start(self, params: dict[str, Any], *, kind: str = "normal") -> dict[str, Any]:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        job = {
            "job_id": job_id,
            "kind": kind,
            "demo": kind == "demo",
            "seed": params.get("seed_question"),
            "domain": params.get("domain"),
            "subject_area": params.get("subject_area"),
            "difficulty_shift": params.get("difficulty_shift"),
            "status": "queued",
            "current_stage": "queued",
            "current": {},
            "requested_count": params.get("count", 1),
            "generated_count": 0,
            "accepted_count": 0,
            "review_count": 0,
            "rejected_count": 0,
            "regeneration_attempts": 0,
            "results": [],
            "summary": None,
            "seed_metadata": None,
            "timings_ms": {},
            "warnings": [],
            "errors": [],
            "started_at": storage.utc_now(),
            "completed_at": None,
            "elapsed_s": 0.0,
            "demo_label": demo.DEMO_LABEL if kind == "demo" else None,
        }
        with self._lock:
            self._jobs[job_id] = job
            while len(self._jobs) > _MAX_JOBS:
                oldest = next(iter(self._jobs))
                if self._jobs[oldest]["status"] in ("completed", "failed"):
                    self._jobs.pop(oldest)
                else:
                    break

        thread = threading.Thread(
            target=self._run, args=(job_id, params, kind), name=f"job-{job_id}", daemon=True
        )
        thread.start()
        return self.get(job_id, include_results=False)

    def get(self, job_id: str, *, include_results: bool = True) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            snapshot = copy.deepcopy(job) if include_results else {
                k: copy.deepcopy(v) for k, v in job.items() if k != "results"
            }
        return snapshot

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            jobs = list(self._jobs.values())[-limit:]
            return [
                {k: copy.deepcopy(v) for k, v in j.items() if k != "results"}
                for j in reversed(jobs)
            ]

    def wait_idle(self, timeout: float = 60.0) -> bool:
        """Block until no job is queued or running. Returns False on timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                busy = any(j["status"] in ("queued", "running") for j in self._jobs.values())
            if not busy:
                return True
            time.sleep(0.05)
        return False

    # ----------------------------------------------------------------- internal
    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.update(fields)

    def _progress(self, job_id: str, started: float):
        def record(event: dict[str, Any]) -> None:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                job["elapsed_s"] = round(time.monotonic() - started, 1)
                stage = event.get("stage")
                if stage:
                    job["current_stage"] = stage
                job["current"] = {
                    k: v for k, v in event.items() if k not in ("candidate", "stage", "done", "total")
                }
                if stage == "decided" and event.get("candidate") is not None:
                    result = _dump(event["candidate"])
                    job["results"].append(result)
                    job["generated_count"] = len(job["results"])
                    decision = result.get("decision")
                    key = {"PASS": "accepted_count", "REVIEW": "review_count", "REJECT": "rejected_count"}.get(decision)
                    if key:
                        job[key] += 1
                    job["regeneration_attempts"] += max(0, int(result.get("attempts", 1)) - 1)

        return record

    def _run(self, job_id: str, params: dict[str, Any], kind: str) -> None:
        started = time.monotonic()
        self._update(job_id, status="running", current_stage="starting")
        progress = self._progress(job_id, started)
        try:
            if kind == "demo":
                seed, results, summary, timings, warnings, _scenario = demo.run_demo(progress=progress)
            else:
                seed, results, summary, timings, warnings = run_pipeline(
                    params["seed_question"],
                    params["domain"],
                    params["count"],
                    difficulty_shift=params.get("difficulty_shift"),
                    enable_regeneration=params.get("enable_regeneration", True),
                    verify=True,
                    persist=params.get("persist", True),
                    progress=progress,
                    subject_area=params.get("subject_area"),
                )
            with self._lock:
                job = self._jobs[job_id]
                # The final, authoritative list replaces the live one (same content,
                # guaranteed complete and in plan order).
                job["results"] = [_dump(r) for r in results]
                job["generated_count"] = len(results)
                job["accepted_count"] = summary.passed
                job["review_count"] = summary.review
                job["rejected_count"] = summary.rejected
                job["regeneration_attempts"] = summary.regeneration_attempts
                job["summary"] = _dump(summary)
                job["seed_metadata"] = _dump(seed)
                job["timings_ms"] = timings
                job["warnings"] = list(warnings)
                job["status"] = "completed" if results or not warnings else "failed"
                if job["status"] == "failed":
                    job["errors"].extend(warnings)
                job["current_stage"] = "complete"
        except Exception as exc:  # the job must always end in a terminal state
            logger.exception("Job %s failed", job_id)
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "failed"
                job["current_stage"] = "failed"
                job["errors"].append(f"{type(exc).__name__}: {exc}")
        finally:
            self._update(
                job_id,
                completed_at=storage.utc_now(),
                elapsed_s=round(time.monotonic() - started, 1),
            )


jobs = JobManager()
