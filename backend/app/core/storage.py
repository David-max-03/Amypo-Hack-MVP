"""Local JSON storage.

The MVP deliberately uses flat JSON files rather than a database - the technical
documentation scopes storage to local JSON, and it keeps the whole system something
two students can explain end to end. Writes are atomic (temp file + rename) so a
crash mid-write cannot corrupt a store.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import settings

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()

# Every store is a JSON object with a top-level list, so the files stay
# self-describing when a judge opens them.
_DEFAULTS: dict[str, dict[str, Any]] = {
    "question_bank.json": {"questions": []},
    "review_queue.json": {"items": []},
    "validation_report.json": {"reports": []},
    "audit_logs.json": {"events": []},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _path(name: str) -> Path:
    return settings.data_dir / name


def ensure_data_files() -> None:
    """Create data/ and any missing store with its empty skeleton."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    for name, default in _DEFAULTS.items():
        p = _path(name)
        if not p.exists():
            _atomic_write(p, default)
            logger.info("Created empty store %s", p)


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def read_json(name: str, default: Any = None) -> Any:
    """Read a store, returning its declared default when missing or corrupt."""
    p = _path(name)
    fallback = default if default is not None else _DEFAULTS.get(name, {})
    if not p.exists():
        return json.loads(json.dumps(fallback))
    try:
        with p.open(encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        logger.error("Corrupt store %s (%s); returning empty default", p, exc)
        return json.loads(json.dumps(fallback))


def write_json(name: str, payload: Any) -> None:
    with _LOCK:
        _atomic_write(_path(name), payload)


def append_to(name: str, key: str, item: Any, *, cap: int | None = None) -> None:
    """Append one record to a list-bearing store, optionally capping its length."""
    with _LOCK:
        data = read_json(name)
        items = data.setdefault(key, [])
        items.append(item)
        if cap is not None and len(items) > cap:
            del items[: len(items) - cap]
        _atomic_write(_path(name), data)


# ----------------------------------------------------------------------
# Convenience accessors used by the API layer
# ----------------------------------------------------------------------
def load_question_bank() -> list[dict]:
    return read_json("question_bank.json").get("questions", [])


def save_accepted_question(record: dict) -> None:
    append_to("question_bank.json", "questions", record)


def load_review_queue() -> list[dict]:
    return read_json("review_queue.json").get("items", [])


def save_review_item(record: dict) -> None:
    append_to("review_queue.json", "items", record)


def resolve_review_item(item_id: str, action: str, note: str | None = None) -> dict | None:
    """Take an item out of the review queue after a human decision.

    `approve` moves it into the question bank; `reject` records it under
    `resolved` in the review store so the decision stays auditable. Returns the
    resolved record, or None if no queued item has that id.
    """
    with _LOCK:
        queue = read_json("review_queue.json")
        items = queue.get("items", [])
        match = next((i for i in items if i.get("id") == item_id), None)
        if match is None:
            return None
        queue["items"] = [i for i in items if i.get("id") != item_id]

        resolved = {
            **match,
            "review_decision": action,
            "review_note": note,
            "reviewed_at": utc_now(),
        }
        if action == "approve":
            resolved["decision"] = "PASS"
            resolved["validation_status"] = "approved by human reviewer"
            bank = read_json("question_bank.json")
            bank.setdefault("questions", []).append(resolved)
            _atomic_write(_path("question_bank.json"), bank)
        else:
            resolved["decision"] = "REJECT"
            resolved["validation_status"] = "rejected by human reviewer"
            queue.setdefault("resolved", []).append(resolved)
        _atomic_write(_path("review_queue.json"), queue)
    audit(f"review_{action}", id=item_id, question=str(match.get("question", ""))[:200])
    return resolved


def save_validation_report(record: dict) -> None:
    # Keep the report file readable during a demo rather than unbounded.
    append_to("validation_report.json", "reports", record, cap=200)


def audit(event: str, **fields: Any) -> None:
    """Append one audit event. Never raises - auditing must not break a pipeline run."""
    try:
        append_to(
            "audit_logs.json",
            "events",
            {"ts": utc_now(), "event": event, **fields},
            cap=1000,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to write audit event %s: %s", event, exc)


def accepted_question_texts() -> list[str]:
    """Question strings already accepted - the memory PS8 dedupes against."""
    return [q.get("question", "") for q in load_question_bank() if q.get("question")]
