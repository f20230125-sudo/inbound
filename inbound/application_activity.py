"""Append human declarations to the existing timeline, independently of pack review."""

import json
from datetime import UTC, date, datetime

from inbound.extract.pipeline import latest_revision
from inbound.ledger import timestamp
from inbound.pause import check
from inbound.steps import Empty, Kind, emit


class ActivityConflict(RuntimeError):
    """The reader's revision or activity is no longer current."""


def latest(db, opportunity_id):
    row = db.execute(
        "SELECT id,created_at,details_json FROM review_events WHERE opportunity_id=? "
        "AND action='applied_outside' ORDER BY id DESC LIMIT 1", (opportunity_id,),
    ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "recorded_at": row["created_at"], **json.loads(row["details_json"])}


def applied_time(value):
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("An ISO date and time with timezone is required")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Applied time requires a timezone")
    return parsed.astimezone(UTC).isoformat()


def record(
    db, opportunity_id, *, applied_at, human_submission, expected_revision_id,
    expected_activity_id, note="", follow_up=None, mode="local", expected_content_version=0,
):
    if mode != "local":
        raise ValueError("Outside applications are available in local mode")
    if human_submission is not True:
        raise ValueError("Explicit human declaration required")
    applied_at = applied_time(applied_at)
    if not isinstance(note, str) or len(note) > 1000:
        raise ValueError("Note must be at most 1000 characters")
    if follow_up is not None and (
        not isinstance(follow_up, str) or date.fromisoformat(follow_up).isoformat() != follow_up
    ):
        raise ValueError("Follow-up requires YYYY-MM-DD")
    if type(expected_revision_id) is not int or (
        expected_activity_id is not None and type(expected_activity_id) is not int
    ):
        raise ValueError("Expected revision and activity required")
    details = {"applied_at": applied_at, "note": note, "follow_up": follow_up,
               "human_submission": True}
    db.execute("BEGIN IMMEDIATE")
    with db:
        check(db)
        if db.execute("SELECT 1 FROM runs WHERE status='running' AND operation_key='import'").fetchone():
            raise ActivityConflict("Import is running; wait for its snapshot")
        if not db.execute("SELECT 1 FROM opportunities WHERE id=?", (opportunity_id,)).fetchone():
            raise LookupError("Opportunity not found")
        revision = latest_revision(db, opportunity_id)
        version = db.execute("SELECT content_version FROM opportunities WHERE id=?",
                             (opportunity_id,)).fetchone()[0]
        previous = latest(db, opportunity_id)
        if revision["id"] != expected_revision_id or version != expected_content_version:
            raise ActivityConflict("This opportunity changed. Reload the latest revision.")
        # A lost response may be retried using the version from before this exact write.
        if previous and all(previous[k] == v for k, v in details.items()) and (
            expected_activity_id in {previous["id"], previous["previous_activity_id"]}
        ):
            return previous
        if expected_activity_id != (previous["id"] if previous else None):
            raise ActivityConflict("The outside application changed. Reload before correcting it.")
        details["previous_activity_id"] = previous["id"] if previous else None
        db.execute(
            "INSERT INTO review_events(opportunity_id,revision_id,action,created_at,details_json) "
            "VALUES (?,?,'applied_outside',?,?)",
            (opportunity_id, revision["id"], timestamp(), json.dumps(details)),
        )
        emit(db, Kind.APPLIED, Empty(), entity_type="opportunity", entity_id=opportunity_id,
             revision_id=revision['id'])
        return latest(db, opportunity_id)
