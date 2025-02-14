"""Run metadata is deliberately allowlisted; exception text is never persisted."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime

COUNTS = {
    "imported",
    "unchanged",
    "changed",
    "triaged",
    "evaluated",
    "messages",
    "opportunities",
    "revisions",
    "blocked",
    "attacks",
    "built",
    "projects",
    "skills",
}


def timestamp():
    return datetime.now(UTC).isoformat()


@contextmanager
def run(db, kind):
    if kind not in {"import", "triage", "extract", "baseline", "extract_baseline",
                    "evidence", "pack", "pack_eval"}:
        raise ValueError("Unknown run kind")
    cursor = db.execute(
        "INSERT INTO runs(kind,started_at,status) VALUES (?,?,'running')", (kind, timestamp())
    )
    run_id = cursor.lastrowid
    db.commit()
    counts = {}
    status, error = "success", None
    try:
        yield counts
    except Exception as exc:
        status, error = "failed", type(exc).__name__
        raise
    finally:
        safe_counts = {k: v for k, v in counts.items() if k in COUNTS and type(v) is int and v >= 0}
        db.execute(
            "UPDATE runs SET finished_at=?,status=?,counts_json=?,error=? WHERE id=?",
            (timestamp(), status, json.dumps(safe_counts, sort_keys=True), error, run_id),
        )
        db.commit()
