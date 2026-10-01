"""The integrated PS8 + PS2 endpoint."""

from __future__ import annotations

import logging
import threading
import time

from fastapi import APIRouter, HTTPException

from .. import demo
from ..pipeline import run_pipeline
from ..schemas import DemoRunRequest, GenerateAndVerifyRequest, GenerateAndVerifyResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Integrated"])

# Live progress for runs that supplied a job_id. In-memory and bounded: it only has to
# outlive one UI polling session, not a restart.
_PROGRESS: dict[str, dict] = {}
_PROGRESS_LOCK = threading.Lock()
_PROGRESS_MAX_JOBS = 50


def _progress_recorder(job_id: str):
    started = time.monotonic()

    def record(event: dict) -> None:
        with _PROGRESS_LOCK:
            job = _PROGRESS.setdefault(job_id, {"job_id": job_id, "decisions": []})
            if event.get("stage") == "decided":
                job["decisions"].append(
                    {k: event[k] for k in ("variation", "decision", "attempts")}
                )
            job.update({k: v for k, v in event.items() if k not in ("decision", "candidate")})
            job["elapsed_s"] = round(time.monotonic() - started, 1)
            while len(_PROGRESS) > _PROGRESS_MAX_JOBS:
                _PROGRESS.pop(next(iter(_PROGRESS)))

    return record


@router.get("/progress/{job_id}", summary="Live progress of a generate-and-verify run")
def get_progress(job_id: str) -> dict:
    with _PROGRESS_LOCK:
        job = _PROGRESS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"No run with job_id {job_id!r} yet")
        return dict(job, decisions=list(job["decisions"]))


@router.post(
    "/generate-and-verify",
    response_model=GenerateAndVerifyResponse,
    summary="Run the full pipeline: generate -> validate -> verify -> decide -> regenerate",
)
def generate_and_verify(request: GenerateAndVerifyRequest) -> GenerateAndVerifyResponse:
    """Execute the complete Code Titans trust pipeline for one seed question."""
    recorder = _progress_recorder(request.job_id) if request.job_id else None
    seed, results, summary, timings, warnings = run_pipeline(
        request.seed_question,
        request.domain,
        request.count,
        difficulty_shift=request.difficulty_shift,
        enable_regeneration=request.enable_regeneration,
        verify=True,
        persist=request.persist,
        progress=recorder,
    )
    if recorder is not None:
        recorder({"stage": "complete", "total": request.count, "done": len(results)})

    if not results and warnings:
        raise HTTPException(status_code=503, detail=warnings[0])

    return GenerateAndVerifyResponse(
        seed_metadata=seed,
        results=results,
        summary=summary,
        timings_ms=timings,
        warnings=warnings,
    )


@router.post(
    "/demo/run",
    response_model=GenerateAndVerifyResponse,
    summary="DEMO: deterministic reject -> regenerate -> pass run of the real pipeline",
)
def run_demo(request: DemoRunRequest | None = None) -> GenerateAndVerifyResponse:
    """Replay the scripted demo candidates through the real validation pipeline.

    Only the model call is scripted; every score, verdict and decision is computed
    live. Results are labelled DEMO and never written to any store.
    """
    job_id = request.job_id if request else None
    recorder = _progress_recorder(job_id) if job_id else None
    seed, results, summary, timings, warnings, scenario = demo.run_demo(progress=recorder)
    if recorder is not None:
        recorder({"stage": "complete", "total": 1, "done": len(results)})
    return GenerateAndVerifyResponse(
        seed_metadata=seed,
        results=results,
        summary=summary,
        timings_ms=timings,
        warnings=warnings,
        demo=True,
        demo_label=demo.DEMO_LABEL,
        demo_description=scenario["description"],
    )
