"""Storage endpoints: question bank, review queue, reports, audit log and export."""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse

from ..core import storage

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Storage"])


@router.get("/questions", summary="Accepted question bank")
def get_questions(limit: int = Query(default=200, ge=1, le=1000)) -> dict:
    items = storage.load_question_bank()
    return {"count": len(items), "questions": items[-limit:]}


@router.get("/review-queue", summary="Questions awaiting human review")
def get_review_queue(limit: int = Query(default=200, ge=1, le=1000)) -> dict:
    items = storage.load_review_queue()
    return {"count": len(items), "items": items[-limit:]}


class ReviewAction(BaseModel):
    note: str | None = Field(default=None, max_length=500)


def _resolve(item_id: str, action: str, body: ReviewAction | None) -> dict:
    record = storage.resolve_review_item(item_id, action, body.note if body else None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No review item with id {item_id!r}")
    return {"id": item_id, "review_decision": action, "record": record}


@router.post("/review-queue/{item_id}/approve", summary="Approve a review item into the bank")
def approve_review_item(item_id: str, body: ReviewAction | None = None) -> dict:
    return _resolve(item_id, "approve", body)


@router.post("/review-queue/{item_id}/reject", summary="Reject a review item")
def reject_review_item(item_id: str, body: ReviewAction | None = None) -> dict:
    return _resolve(item_id, "reject", body)


def _filtered_reports(job_id: str | None, since_hours: float | None) -> list[dict]:
    reports = storage.read_json("validation_report.json").get("reports", [])
    if job_id:
        reports = [r for r in reports if r.get("job_id") == job_id]
    if since_hours:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        kept = []
        for r in reports:
            try:
                if datetime.fromisoformat(r["created_at"]) >= cutoff:
                    kept.append(r)
            except (KeyError, TypeError, ValueError):
                continue  # no usable timestamp: cannot be placed inside a time window
        reports = kept
    return reports


@router.get("/validation-reports", summary="Combined PS8 + PS2 validation reports")
def get_validation_reports(
    limit: int = Query(default=50, ge=1, le=200),
    job_id: str | None = Query(default=None, description="Only reports from this generation job"),
    since_hours: float | None = Query(default=None, gt=0, description="Only reports newer than this"),
) -> dict:
    reports = _filtered_reports(job_id, since_hours)
    return {"count": len(reports), "reports": reports[-limit:]}


@router.get("/validation-reports/stats", summary="PASS / REVIEW / REJECT counts and the runs on record")
def get_validation_report_stats(
    job_id: str | None = Query(default=None),
    since_hours: float | None = Query(default=None, gt=0),
) -> dict:
    """Decision statistics computed from the stored reports (never estimated)."""
    reports = _filtered_reports(job_id, since_hours)
    total = len(reports)
    decisions = {}
    for name in ("PASS", "REVIEW", "REJECT"):
        n = sum(1 for r in reports if r.get("decision") == name)
        decisions[name] = {"count": n, "percent": round(100.0 * n / total, 1) if total else 0.0}

    # Runs are listed from every stored report, so the run filter never hides itself.
    runs: dict[str, dict] = {}
    for r in storage.read_json("validation_report.json").get("reports", []):
        rid = r.get("job_id")
        if not rid:
            continue
        run = runs.setdefault(rid, {
            "job_id": rid, "seed_question": r.get("seed_question"),
            "subject_area": r.get("subject_area"), "first_at": r.get("created_at"), "reports": 0,
        })
        run["reports"] += 1
        run["last_at"] = r.get("created_at")
    regenerated = sum(1 for r in reports if int(r.get("attempts") or 1) > 1)
    return {
        "total": total,
        "decisions": decisions,
        "regenerated": regenerated,
        "regeneration_rate": round(regenerated / total, 3) if total else 0.0,
        "runs": sorted(runs.values(), key=lambda x: x.get("last_at") or "", reverse=True),
        "reports_without_run": sum(
            1 for r in storage.read_json("validation_report.json").get("reports", []) if not r.get("job_id")
        ),
    }


@router.get("/audit-logs", summary="Audit trail")
def get_audit_logs(limit: int = Query(default=100, ge=1, le=1000)) -> dict:
    events = storage.read_json("audit_logs.json").get("events", [])
    return {"count": len(events), "events": events[-limit:]}


_CSV_COLUMNS = [
    "id", "question", "answer_key", "domain", "topic", "subtopic", "difficulty",
    "difficulty_score", "question_type", "learning_objective", "variation_strategy",
    "solution_method", "reliability_score", "verdict", "hallucination_probability",
    "decision", "validation_status", "attempts", "seed_question", "created_at",
]


@router.get("/export", summary="Export the question bank as JSON or CSV")
def export_bank(fmt: str = Query(default="json", pattern="^(json|csv)$")):
    """Bulk export module (PS8 mandatory component)."""
    questions = storage.load_question_bank()

    if fmt == "json":
        return {"count": len(questions), "questions": questions}

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for q in questions:
        writer.writerow({k: q.get(k, "") for k in _CSV_COLUMNS})
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="question_bank.csv"'},
    )
