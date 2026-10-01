"""Storage endpoints: question bank, review queue, reports, audit log and export."""

from __future__ import annotations

import csv
import io
import logging

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


@router.get("/validation-reports", summary="Combined PS8 + PS2 validation reports")
def get_validation_reports(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    reports = storage.read_json("validation_report.json").get("reports", [])
    return {"count": len(reports), "reports": reports[-limit:]}


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
