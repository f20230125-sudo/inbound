"""Stored snapshot summaries shared by the desk and the plain-text CLI."""

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from inbound.extract.pipeline import latest_revision, opportunity_state
from inbound.presentation import opportunity_labels
from inbound.triage.normalize import normalize_subject

DUBAI = ZoneInfo("Asia/Dubai")


def snapshot_metadata(db, now):
    row = db.execute("SELECT * FROM snapshots ORDER BY version DESC LIMIT 1").fetchone()
    result = (
        dict(row)
        if row
        else {
            "version": 0,
            "imported_at": None,
            "latest_message_at": None,
            "run_id": None,
        }
    )
    imported = datetime.fromisoformat(result["imported_at"]) if row else None
    result["stale"] = imported is None or (
        now - imported > timedelta(hours=12)
        or imported.astimezone(DUBAI).date() < now.astimezone(DUBAI).date()
    )
    failure = db.execute(
        "SELECT id,finished_at,error,status FROM runs WHERE kind='import' "
        "AND status IN ('failed','paused','blocked') ORDER BY id DESC LIMIT 1"
    ).fetchone()
    result["latest_import_failure"] = (
        dict(failure) if failure and (not row or failure["id"] > (row["run_id"] or 0)) else None
    )
    return result


def deadline_group(record, now):
    if not record or record["status"] not in {"found", "inferred"}:
        return "uncertain"
    value = record["normalized"]
    if not value:
        return "uncertain"
    if len(value) == 10:
        day = datetime.fromisoformat(value).date()
        delta = (day - now.astimezone(DUBAI).date()).days
        return "date_only" if delta in {0, 1} else ("overdue" if delta < 0 else "later")
    due = datetime.fromisoformat(value)
    return "overdue" if due <= now else ("timed" if due <= now + timedelta(hours=48) else "later")


def today(db, now=None):
    now = now or datetime.now(UTC)
    result = {
        "now": now.isoformat(),
        "timezone": "Asia/Dubai",
        "paused": db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0] == "1",
        "snapshot": snapshot_metadata(db, now),
        "attention": [],
        "deadlines_48h": [],
        "date_only": [],
        "uncertain_deadlines": [],
        "new_calls": [],
        "admin_tasks": [],
    }
    entries = []
    for row in db.execute("SELECT id FROM opportunities"):
        state = opportunity_state(db, row["id"], clock=lambda: now)
        if state["status"] in {"submitted_by_me", "skipped"}:
            continue
        revision = latest_revision(db, row["id"])
        message = db.execute(
            "SELECT * FROM messages WHERE id=?", (revision["message_id"],)
        ).fetchone()
        entries.append(
            {
                "id": state["id"],
                "kind": "call",
                "company": state["fields"]["company"]["normalized"],
                "city": state["fields"]["city"]["normalized"],
                "roles": state["fields"]["roles"]["normalized"],
                "status": state["status"],
                "mode": state["fields"]["mode"]["normalized"],
                "stipend": state["fields"]["stipend"]["normalized"],
                "deadline": state["fields"]["deadline"],
                "blocked_reason": state["blocked_reason"],
                "conflicts": [
                    name
                    for name, record in state["fields"].items()
                    if record["status"] == "conflicting"
                ],
                "updated_at": state["updated_at"],
                "received_at": message["received_at"],
                "provider_id": message["provider_id"],
                "subject": message["subject"],
                **opportunity_labels(db, state, message["subject"]),
            }
        )
    for row in db.execute(
        "SELECT m.*,e.fields_json FROM messages m JOIN triage t ON t.message_id=m.id "
        "LEFT JOIN message_extractions e ON e.message_id=m.id "
        "WHERE COALESCE(t.corrected_category,t.category)='ps_admin'"
    ):
        fields = json.loads(row["fields_json"] or "{}")
        entries.append(
            {
                "id": row["id"],
                "kind": "ps_admin",
                "subject": row["subject"],
                "provider_id": row["provider_id"],
                "received_at": row["received_at"],
                "deadline": fields.get("admin_deadline"),
                "blocked_reason": None,
                "conflicts": [],
            }
        )
    for entry in entries:
        if entry["kind"] == "ps_admin":
            entry["display_title"] = normalize_subject(entry["subject"])
        group = deadline_group(entry["deadline"], now)
        entry["deadline_group"] = group
        entry["deadline_label"] = (
            "Deadline passed"
            if group == "overdue" and entry["kind"] == "ps_admin"
            else "Expired"
            if group == "overdue"
            else "Deadline conflicting — review required"
            if entry["deadline"] and entry["deadline"]["status"] == "conflicting"
            else "Deadline unknown — expiry unknown"
            if group == "uncertain"
            else "Due today — time not stated"
            if group == "date_only"
            and entry["deadline"]["normalized"] == now.astimezone(DUBAI).date().isoformat()
            else "Due tomorrow — time not stated"
            if group == "date_only"
            else "Supported deadline"
        )
        if entry["deadline"] and entry["deadline"].get("past_at_receipt"):
            entry["deadline_label"] += " · Deadline passed before receipt"
        entry["attention_reason"] = (
            "Deadline conflicting — review required"
            if entry["deadline"] and entry["deadline"]["status"] == "conflicting"
            else "Blocked: " + entry["blocked_reason"]
            if entry["blocked_reason"]
            else "Conflicting fields — review required: " + ", ".join(entry["conflicts"])
            if entry["conflicts"]
            else entry["deadline_label"]
        )
        if (
            entry["blocked_reason"]
            or entry["conflicts"]
            or (entry["deadline"] and entry["deadline"]["status"] == "conflicting")
            or group == "overdue"
        ):
            result["attention"].append(entry)
        if group == "timed":
            result["deadlines_48h"].append(entry)
        elif group == "date_only":
            result["date_only"].append(entry)
        elif group == "uncertain" and entry["kind"] == "call":
            result["uncertain_deadlines"].append(entry)
        if entry["kind"] == "call" and entry["status"] == "new":
            result["new_calls"].append(entry)
        elif entry["kind"] == "ps_admin":
            result["admin_tasks"].append(entry)

    def due(entry):
        record = entry["deadline"] or {}
        candidates = record.get("candidates", [record])
        return min((c["normalized"] for c in candidates if c.get("normalized")), default="9999")

    def received(entry):
        return -datetime.fromisoformat(entry["received_at"]).timestamp(), str(entry["id"])

    def attention_order(entry):
        if entry["blocked_reason"] or entry["conflicts"]:
            updated = datetime.fromisoformat(entry.get("updated_at", entry["received_at"]))
            return (0, due(entry), -updated.timestamp(), str(entry["id"]))
        return (1, -datetime.fromisoformat(due(entry)).timestamp(), str(entry["id"]))

    result["attention"].sort(key=attention_order)
    for key in ("deadlines_48h", "date_only"):
        result[key].sort(key=lambda e: (due(e), str(e["id"])))
    result["new_calls"].sort(key=received)
    result["admin_tasks"].sort(
        key=lambda e: (
            {"timed": 0, "date_only": 1, "overdue": 2, "later": 3, "uncertain": 4}[
                e["deadline_group"]
            ],
            due(e),
            *received(e),
        )
    )
    return result


def plain_text(summary):
    snapshot = summary["snapshot"]

    def display(value):
        if not value:
            return "Not recorded"
        if len(value) == 10:
            return value + " · Time not stated"
        return datetime.fromisoformat(value).astimezone(DUBAI).strftime("%d %b %Y, %H:%M")

    lines = [
        "Today / Inbox",
        "Dubai time · UTC+04:00",
        "Paused — imports, extraction and pack work are stopped."
        if summary["paused"]
        else "Work enabled",
        f"Last successful import: {display(snapshot['imported_at'])}",
        f"Latest message in that import: {display(snapshot['latest_message_at'])}",
    ]
    if snapshot["stale"]:
        lines += ["Snapshot may be out of date", "New mail may be missing."]
    if snapshot["latest_import_failure"]:
        lines += ["Latest import failed. Showing the last successful snapshot."]
    for label, key in [
        ("Overdue / blocked", "attention"),
        ("Deadlines within 48 hours", "deadlines_48h"),
        ("Date-only deadlines", "date_only"),
        ("Unknown / conflicting deadlines", "uncertain_deadlines"),
        ("New calls", "new_calls"),
        ("PS administration", "admin_tasks"),
    ]:
        lines += ["", label]
        for row in summary[key]:
            value = (row["deadline"] or {}).get("normalized")
            deadline = display(value) if value else "Unknown"
            lines.append(
                f"{row['kind']} · {row['display_title']} · {deadline} · "
                f"{row['attention_reason']}"
            )
    return "\n".join(lines) + "\n"
