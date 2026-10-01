"""Background generation jobs and the shared taxonomy."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import taxonomy
from ..jobs import jobs
from ..schemas import JobRequest

router = APIRouter(tags=["Jobs"])


@router.get("/taxonomy", summary="The one shared domain / difficulty configuration")
def get_taxonomy() -> dict:
    return taxonomy.as_dict()


@router.post("/jobs", status_code=202, summary="Start a background generate-and-verify job")
def start_job(request: JobRequest) -> dict:
    domain = request.domain
    if request.subject_area:
        mapped = taxonomy.pipeline_domain_for(request.subject_area)
        if mapped is None:
            raise HTTPException(status_code=422, detail=f"Unknown subject area {request.subject_area!r}")
        domain = mapped
    params = {**request.model_dump(), "domain": domain}
    return jobs.start(params, kind="normal")


@router.post("/jobs/demo", status_code=202, summary="DEMO: start the deterministic demo scenario as a job")
def start_demo_job() -> dict:
    return jobs.start({"seed_question": None, "domain": "programming", "count": 1}, kind="demo")


@router.get("/jobs", summary="Recent jobs (without candidate results)")
def list_jobs(limit: int = Query(default=20, ge=1, le=50)) -> dict:
    items = jobs.list(limit)
    return {"count": len(items), "jobs": items}


@router.get("/jobs/{job_id}", summary="Live state of one job, including candidate results")
def get_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job {job_id!r} (jobs live until the backend restarts)")
    return job
