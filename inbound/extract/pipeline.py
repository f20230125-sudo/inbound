"""Persist local evidence and effective revisions in sent-time order."""

import json
from copy import deepcopy
from datetime import UTC, datetime

from inbound.extract.attachments import parse_attachment
from inbound.extract.call import extract_call
from inbound.extract.deadline import expired
from inbound.extract.records import conflict
from inbound.ledger import timestamp
from inbound.models import Attachment, Message
from inbound.pause import check
from inbound.triage.normalize import normalize_subject
from inbound.triage.rules import urgency


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def message_from_row(row, attachments):
    return Message(
        provider_id=row["provider_id"],
        provider=row["provider"],
        thread_id=row["thread_id"],
        sent_at=datetime.fromisoformat(row["sent_at"]),
        received_at=datetime.fromisoformat(row["received_at"]),
        sender=row["sender"],
        subject=row["subject"],
        body_text=row["body_text"],
        source=row["source"],
        body_complete=bool(row["body_complete"]),
        attachments=tuple(attachments),
    )


def invalidate_reviewed_packs(db, opportunity_id):
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='packs'").fetchone():
        db.execute(
            "UPDATE packs SET status='needs_review' WHERE opportunity_id=? AND status='reviewed'",
            (opportunity_id,),
        )


def comparable(record):
    value = record["normalized"]
    if record["name"] == "roles" and value:
        return [
            (
                r["title"],
                [q["text"] for q in r["requirements"]] if r["requirements"] is not None else None,
            )
            for r in value
        ]
    return value


def column(value):
    return dump(value) if isinstance(value, (list, dict)) else value


def effective_fields(previous, current, amendment):
    effective = deepcopy(previous)
    for name, candidate in current.items():
        old = previous.get(name)
        if old is None or old["status"] == "unknown":
            effective[name] = deepcopy(candidate)
        elif candidate["status"] == "unknown":
            continue
        elif (
            (
                comparable(old) == comparable(candidate)
                and old["status"] != "conflicting"
                and candidate["status"] != "conflicting"
            )
            or name == "deadline"
            and amendment
        ):
            effective[name] = deepcopy(candidate)
        else:
            effective[name] = conflict(name, [old, candidate])
    return effective


def explicit_links(fields):
    links = set()
    for name in ("form_link", "apply_link"):
        record = fields[name]
        for candidate in record.get("candidates", [record]):
            if candidate["status"] == "found":
                links.add(candidate["normalized"])
    return links


def matching_opportunities(db, row, fields):
    matches, different_links = set(), set()
    links = explicit_links(fields)
    prior_opportunities = {}
    for revision in db.execute(
        "SELECT r.opportunity_id,r.local_fields_json,m.thread_id,m.subject,m.provider,m.source "
        "FROM opportunity_revisions r JOIN messages m ON m.id=r.message_id"
    ):
        if row["source"] != revision["source"]:
            continue
        prior = prior_opportunities.setdefault(
            revision["opportunity_id"], {"links": set(), "subjects": set(), "threads": set()}
        )
        prior["links"].update(explicit_links(json.loads(revision["local_fields_json"])))
        prior["subjects"].add(normalize_subject(revision["subject"]).casefold())
        if revision["thread_id"]:
            prior["threads"].add((revision["provider"], revision["thread_id"]))
    for identity, prior in prior_opportunities.items():
        if (row["provider"], row["thread_id"]) in prior["threads"] or links & prior["links"]:
            matches.add(identity)
        elif normalize_subject(row["subject"]).casefold() in prior["subjects"]:
            if links and prior["links"]:
                different_links.add(identity)
            else:
                matches.add(identity)
    return matches, different_links


def suggest_merge(db, opportunity_id, candidate_id, message_id, reason):
    if candidate_id != opportunity_id:
        db.execute(
            "INSERT INTO merge_suggestions "
            "(opportunity_id,candidate_id,message_id,reason) VALUES (?,?,?,?) "
            "ON CONFLICT(opportunity_id,candidate_id) DO UPDATE SET reason=excluded.reason "
            "WHERE excluded.reason='same_subject_different_link'",
            (opportunity_id, candidate_id, message_id, reason),
        )


def latest_revision(db, opportunity_id):
    return db.execute(
        "SELECT r.* FROM opportunity_revisions r JOIN messages m ON m.id=r.message_id "
        "WHERE r.opportunity_id=? ORDER BY julianday(m.sent_at) DESC,m.id DESC LIMIT 1",
        (opportunity_id,),
    ).fetchone()


def opportunity_state(db, opportunity_id, clock=None):
    row = db.execute("SELECT * FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
    if row is None:
        raise ValueError("Unknown opportunity")
    revision = latest_revision(db, opportunity_id)
    fields = json.loads(revision["fields_json"])
    now = (clock or (lambda: datetime.now(UTC)))()
    return {
        **dict(row),
        "revision_id": revision["id"],
        "fields": fields,
        "expired": expired(fields["deadline"], now),
    }


def sync_revision(db, opportunity_id, revision_id, effective):
    db.execute(
        "UPDATE opportunity_revisions SET fields_json=? WHERE id=?", (dump(effective), revision_id)
    )
    for name, f in effective.items():
        db.execute(
            "INSERT INTO fields(opportunity_id,revision_id,name,raw,normalized,status,"
            "source_text,record_json) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(revision_id,name) DO UPDATE SET raw=excluded.raw,"
            "normalized=excluded.normalized,status=excluded.status,"
            "source_text=excluded.source_text,record_json=excluded.record_json",
            (
                opportunity_id,
                revision_id,
                name,
                f["raw"],
                dump(f["normalized"]),
                f["status"],
                f["source_text"],
                dump(f),
            ),
        )
    existing = db.execute(
        "SELECT id FROM roles WHERE revision_id=? ORDER BY id", (revision_id,)
    ).fetchall()
    roles = effective["roles"]["normalized"] or []
    for i, role in enumerate(roles):
        values = (role["title"], dump(role["requirements"]), dump(effective["roles"]))
        if i < len(existing):
            db.execute(
                "UPDATE roles SET title=?,requirements_json=?,source_record_json=? WHERE id=?",
                (*values, existing[i]["id"]),
            )
        else:
            db.execute(
                "INSERT INTO roles(title,requirements_json,source_record_json,"
                "opportunity_id,revision_id) VALUES (?,?,?,?,?)",
                (*values, opportunity_id, revision_id),
            )
    for extra in existing[len(roles) :]:
        db.execute("DELETE FROM roles WHERE id=?", (extra["id"],))


def rebuild_timeline(db, opportunity_id):
    """Recompute derived snapshots on late arrival; original local evidence never changes."""
    revisions = db.execute(
        "SELECT r.* FROM opportunity_revisions r JOIN messages m ON m.id=r.message_id "
        "WHERE r.opportunity_id=? ORDER BY julianday(m.sent_at),m.id",
        (opportunity_id,),
    ).fetchall()
    effective, blocker = {}, None
    for revision in revisions:
        check(db)
        local = json.loads(revision["local_fields_json"])
        effective = effective_fields(effective, local, bool(revision["amendment"]))
        if revision["blocked_reason"]:
            blocker = revision["blocked_reason"]
        elif local["jd_location"]["normalized"] == "attached":
            blocker = None
        sync_revision(db, opportunity_id, revision["id"], effective)
    db.execute(
        "UPDATE opportunities SET company=?,city=?,blocked_reason=?,updated_at=? WHERE id=?",
        (
            column(effective["company"]["normalized"]),
            column(effective["city"]["normalized"]),
            blocker,
            timestamp(),
            opportunity_id,
        ),
    )
    if blocker:
        db.execute("UPDATE opportunities SET status='blocked' WHERE id=?", (opportunity_id,))
    else:
        db.execute(
            "UPDATE opportunities SET status='needs_review' WHERE id=? AND status='blocked'",
            (opportunity_id,),
        )


def refresh_urgency(db, now):
    rows = db.execute("SELECT message_id,fields_json FROM message_extractions").fetchall()
    for row in rows:
        fields = json.loads(row["fields_json"])
        opportunity = db.execute(
            "SELECT opportunity_id FROM opportunity_revisions WHERE message_id=?",
            (row["message_id"],),
        ).fetchone()
        if opportunity:
            fields = json.loads(latest_revision(db, opportunity[0])["fields_json"])
        deadline = fields.get("deadline", fields.get("admin_deadline", {}))
        value = (
            deadline.get("normalized") if deadline.get("status") in {"found", "inferred"} else None
        )
        db.execute(
            "UPDATE triage SET urgency=? WHERE message_id=?",
            (urgency(value, now), row["message_id"]),
        )


def extract_messages(db, clock=None, ids=None):
    check(db)
    now = (clock or (lambda: datetime.now(UTC)))()
    if now.tzinfo is None:
        raise ValueError("Extraction clock must be timezone-aware")
    counts = {"messages": 0, "opportunities": 0, "revisions": 0, "blocked": 0, "attacks": 0}
    rows = db.execute(
        "SELECT m.* FROM messages m JOIN triage t ON t.message_id=m.id "
        "ORDER BY julianday(m.sent_at),m.id"
    ).fetchall()
    for row in rows:
        if ids is not None and row["id"] not in ids:
            continue
        check(db)
        if db.execute(
            "SELECT 1 FROM message_extractions WHERE message_id=?", (row["id"],)
        ).fetchone():
            continue
        attachments = db.execute(
            "SELECT * FROM attachments WHERE message_id=?", (row["id"],)
        ).fetchall()
        declarations, parsed = [], []
        for a in attachments:
            check(db)
            declaration = Attachment(
                a["filename"],
                a["mime"],
                a["bytes_path"],
                bool(a["bytes_available"]),
                a["parse_status"],
                a["import_root"],
                a["content_base64"],
            )
            declarations.append(declaration)
            parsed.append(parse_attachment(declaration))
        check(db)
        extracted = extract_call(message_from_row(row, declarations), parsed)
        check(db)
        with db:
            for attachment, result in zip(attachments, parsed, strict=True):
                db.execute(
                    "UPDATE attachments SET text=?,parse_status=? WHERE id=?",
                    (result["text"], result["parse_status"], attachment["id"]),
                )
            local = extracted["fields"]
            db.execute(
                "INSERT INTO message_extractions VALUES (?,?,?,?,?)",
                (
                    row["id"],
                    dump(local),
                    int(extracted["attack_suspected"]),
                    dump(extracted["attack_quotes"]),
                    timestamp(),
                ),
            )
            counts["messages"] += 1
            counts["attacks"] += int(extracted["attack_suspected"])
            if not extracted["creates_opportunity"]:
                continue
            check(db)
            matches, different_links = matching_opportunities(db, row, local)
            if len(matches) == 1:
                opportunity_id = matches.pop()
                invalidate_reviewed_packs(db, opportunity_id)
                db.execute(
                    "UPDATE opportunities SET status='needs_review',updated_at=? WHERE id=? "
                    "AND status='reviewed'",
                    (timestamp(), opportunity_id),
                )
            else:
                cursor = db.execute(
                    "INSERT INTO opportunities(company,city,source_thread_id,provider,"
                    "normalized_subject,kind,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        column(local["company"]["normalized"]),
                        column(local["city"]["normalized"]),
                        row["thread_id"],
                        row["provider"],
                        normalize_subject(row["subject"]),
                        extracted["kind"],
                        "new",
                        timestamp(),
                        timestamp(),
                    ),
                )
                opportunity_id = cursor.lastrowid
                counts["opportunities"] += 1
                probable = db.execute(
                    "SELECT id FROM opportunities WHERE company=? AND id<>?",
                    (column(local["company"]["normalized"]), opportunity_id),
                ).fetchall()
                for candidate in {p["id"] for p in probable} | matches:
                    suggest_merge(
                        db,
                        opportunity_id,
                        candidate,
                        row["id"],
                        "Ambiguous identity" if matches else "Company only; no joining evidence",
                    )
            for candidate in different_links:
                suggest_merge(
                    db, opportunity_id, candidate, row["id"], "same_subject_different_link"
                )
            check(db)
            cursor = db.execute(
                "INSERT INTO opportunity_revisions "
                "(opportunity_id,message_id,fields_json,local_fields_json,amendment,"
                "blocked_reason,created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    opportunity_id,
                    row["id"],
                    dump(local),
                    dump(local),
                    int(extracted["amendment"]),
                    extracted["blocked_reason"],
                    timestamp(),
                ),
            )
            rebuild_timeline(db, opportunity_id)
            reason = extracted["blocked_reason"]
            if reason:
                db.execute(
                    "UPDATE opportunities SET status='blocked',blocked_reason=? WHERE id=?",
                    (reason, opportunity_id),
                )
                counts["blocked"] += 1
            db.execute(
                "UPDATE opportunities SET updated_at=? WHERE id=?", (timestamp(), opportunity_id)
            )
            counts["revisions"] += 1
    check(db)
    with db:
        refresh_urgency(db, now)
    return counts
