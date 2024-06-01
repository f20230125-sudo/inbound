"""Explicit, bounded rules. Suggestions have no influence; no rule grants PS trust."""

import hashlib
import json
import re
from email.utils import parseaddr
from uuid import uuid4

from inbound import learning_preferences as preferences
from inbound.learning_preferences import EFFECTS, preference_fit, rank_key, relocation_evidence
from inbound.ledger import timestamp
from inbound.memory import guard
from inbound.steps import Empty, Kind, Reference, emit, provenance
from inbound.triage.normalize import normalize_subject
from inbound.triage.taxonomy import CATEGORIES

__all__ = ["preference_fit", "rank_key", "relocation_evidence"]


class LearningConflict(RuntimeError):
    pass


def mailbox(sender):
    value = parseaddr(sender)[1].casefold()
    return value if re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value) else None


def matches(definition, row):
    return mailbox(row["sender"]) == definition["mailbox"] and (
        definition["subject"] is None
        or normalize_subject(row["subject"]).casefold() == definition["subject"].casefold()
    )


def matching(db, definition, *, replay=False):
    return [
        dict(r)
        for r in db.execute(
            "SELECT m.*,t.corrected_category,t.category FROM messages m "
            "LEFT JOIN triage t ON t.message_id=m.id ORDER BY m.id"
        )
        if (not replay or r["source"] == "synthetic") and matches(definition, r)
    ]


def get(db, rid):
    row = db.execute("SELECT * FROM learned_rules WHERE id=?", (rid,)).fetchone()
    if row is None:
        raise LearningConflict("Rule is no longer available")
    return dict(row)


def public(db, row, *, replay=False):
    definition = json.loads(row["definition_json"])
    sender = row["kind"] == "sender"
    examples = (
        matching(db, definition, replay=replay)
        if sender
        else preferences.examples(db, definition, replay=replay)
    )
    uses = [
        dict(r)
        for r in db.execute(
            "SELECT u.message_id,m.subject,u.used_at,u.version FROM learned_rule_uses u "
            "JOIN messages m ON m.id=u.message_id WHERE u.rule_id=? "
            + ("AND m.source='synthetic' " if replay else "")
            + "ORDER BY u.id DESC LIMIT 5",
            (row["id"],),
        )
    ]
    title = (
        f"Classify {definition['mailbox']} as {definition['category'].replace('_', ' ')}"
        if sender
        else EFFECTS[definition["effect"]]
    )
    return (
        {
            k: row[k]
            for k in (
                "id",
                "kind",
                "status",
                "version",
                "source",
                "origin_type",
                "origin_id",
                "created_at",
                "changed_at",
            )
        }
        | definition
        | {
            "title": title,
            "conflicts": preferences.conflicts(db, row),
            "scope": (
                "Exact mailbox"
                + (
                    f"; subject equals {definition['subject']}"
                    if definition["subject"]
                    else "; any subject"
                )
                + "; future messages only"
                if sender
                else "Opportunity ranking only; never rejection or deadline changes"
            ),
            "match_count": len(examples),
            "examples": [{"message_id": r["id"], "subject": r["subject"]} for r in examples[:5]],
            "recent_uses": uses,
            "versions": [
                dict(r)
                for r in db.execute(
                    "SELECT version,status,changed_at FROM learned_rule_versions WHERE rule_id=? "
                    "ORDER BY version",
                    (row["id"],),
                )
            ],
        }
    )


def view(db, *, replay=False):
    return {
        "rules": [
            public(db, dict(r), replay=replay)
            for r in db.execute(
                "SELECT * FROM learned_rules "
                + ("WHERE source='synthetic' " if replay else "")
                + "ORDER BY created_at DESC,rowid DESC"
            )
        ]
    }


def save(db, kind, definition, *, source, origin_type, origin_id=None, status="suggested"):
    """Caller owns the transaction, including the human action and journal event."""
    guard(db)
    existing = db.execute(
        "SELECT * FROM learned_rules WHERE kind=? AND definition_json=? "
        "AND status IN ('suggested','active') ORDER BY rowid DESC LIMIT 1",
        (kind, json.dumps(definition, sort_keys=True)),
    ).fetchone()
    if existing:
        return public(db, dict(existing))
    rid, now = uuid4().hex, timestamp()
    watermark = db.execute("SELECT COALESCE(MAX(id),0) FROM messages").fetchone()[0]
    db.execute(
        "INSERT INTO learned_rules VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            rid,
            kind,
            status,
            1,
            json.dumps(definition, sort_keys=True),
            source,
            origin_type,
            str(origin_id) if origin_id is not None else None,
            watermark,
            now,
            now,
        ),
    )
    db.execute(
        "INSERT INTO learned_rule_versions VALUES (?,?,?,?,?)",
        (rid, 1, status, json.dumps(definition, sort_keys=True), now),
    )
    emit(
        db,
        Kind.RULE_ACTIVATED if status == "active" else Kind.RULE_SUGGESTED,
        Empty(),
        entity_type="rule",
        entity_id=rid,
        revision_id=1,
        source=source,
    )
    return public(db, get(db, rid))


def suggest_sender(db, message_id, category, *, subject):
    if type(message_id) is not int or not isinstance(category, str) or category not in CATEGORIES:
        raise ValueError("Stored message and supported category required")
    row = db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
    if row is None or not mailbox(row["sender"]):
        raise ValueError("An exact sender mailbox is required")
    if subject is not None:
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 500:
            raise ValueError("A literal subject condition is required")
        subject = normalize_subject(subject)
    definition = {"mailbox": mailbox(row["sender"]), "subject": subject, "category": category}
    if (
        subject is None
        and len({normalize_subject(r["subject"]).casefold() for r in matching(db, definition)}) > 1
    ):
        raise ValueError("This sender has different purposes; add a subject condition")
    if not matches(definition, row):
        raise ValueError("The subject condition must match the selected example")
    return save(
        db, "sender", definition, source=row["source"], origin_type="message", origin_id=message_id
    )


def change(db, rid, action, *, expected_version):
    if action not in {"activate", "undo"} or type(expected_version) is not int:
        raise ValueError("Supported rule action and version required")
    db.execute("BEGIN IMMEDIATE")
    with db:
        guard(db)
        row = get(db, rid)
        if row["version"] != expected_version:
            raise LearningConflict("Rule changed; refresh before saving")
        if (action == "activate" and row["status"] != "suggested") or row["status"] == "undone":
            raise LearningConflict("Rule action is no longer available")
        version, now = row["version"] + 1, timestamp()
        status = "active" if action == "activate" else "undone"
        watermark = db.execute("SELECT COALESCE(MAX(id),0) FROM messages").fetchone()[0]
        db.execute(
            "UPDATE learned_rules SET status=?,version=?,changed_at=?,starts_after_id=? WHERE id=?",
            (status, version, now, watermark, rid),
        )
        db.execute(
            "INSERT INTO learned_rule_versions VALUES (?,?,?,?,?)",
            (rid, version, status, row["definition_json"], now),
        )
        emit(
            db,
            Kind.RULE_ACTIVATED if action == "activate" else Kind.RULE_UNDONE,
            Empty(),
            entity_type="rule",
            entity_id=rid,
            revision_id=version,
        )
        if status == "active":
            preferences.record_uses(db)
    return public(db, get(db, rid))


def use(db, rule, row):
    cursor = db.execute(
        "INSERT OR IGNORE INTO learned_rule_uses(rule_id,version,message_id,content_hash,used_at) "
        "VALUES (?,?,?,?,?)",
        (rule["id"], rule["version"], row["id"], row["content_hash"], timestamp()),
    )
    if cursor.rowcount:
        emit(
            db,
            Kind.RULE_MATCHED,
            Empty(),
            entity_type="rule",
            entity_id=rule["id"],
            revision_id=rule["version"],
            references=(Reference("message", row["id"]),),
        )


def prediction(db, row, baseline):
    """Only future messages learn automatically. Past decisions need an explicit preview."""
    previous = db.execute("SELECT * FROM triage WHERE message_id=?", (row["id"],)).fetchone()
    if previous and previous["rule_id"].startswith("learned:"):
        from inbound.triage.rules import Prediction

        return Prediction(
            previous["category"], previous["rule_id"], previous["reason"], previous["source_quote"]
        )
    if previous and previous["corrected_category"]:
        return baseline
    rules = db.execute(
        "SELECT * FROM learned_rules WHERE kind='sender' AND status='active' "
        "AND starts_after_id<? ORDER BY changed_at DESC,rowid DESC",
        (row["id"],),
    )
    candidates = [dict(r) for r in rules if matches(json.loads(r["definition_json"]), row)]
    # More specific current instructions win over broader rules; newest wins equal scope.
    candidates.sort(key=lambda r: json.loads(r["definition_json"])["subject"] is None)
    if not candidates:
        return baseline
    rule = candidates[0]
    use(db, rule, row)
    return rule_prediction(rule, row)


def rule_prediction(rule, row):
    from inbound.triage.rules import Prediction

    category = json.loads(rule["definition_json"])["category"]
    return Prediction(
        category,
        "learned:" + rule["id"],
        f"Your exact sender rule (version {rule['version']}): {category}",
        row["sender"],
    )


def preview(db, rid, *, replay=False):
    row = get(db, rid)
    if row["kind"] != "sender" or row["status"] != "active":
        raise LearningConflict("Activate a sender rule before previewing reprocessing")
    rows = matching(db, json.loads(row["definition_json"]), replay=replay)
    generation = db.execute("SELECT generation FROM domain_generation WHERE id=1").fetchone()[0]
    token = hashlib.sha256(json.dumps([rid, row["version"], generation]).encode()).hexdigest()
    return {
        "token": token,
        "match_count": len(rows),
        "eligible_count": sum(not r["corrected_category"] for r in rows),
        "examples": [
            {
                "message_id": r["id"],
                "subject": r["subject"],
                "manual_correction": bool(r["corrected_category"]),
            }
            for r in rows[:5]
        ],
    }


def reprocess(db, rid, *, expected_version, expected_token):
    db.execute("BEGIN IMMEDIATE")
    with db:
        guard(db)
        row = get(db, rid)
        current = preview(db, rid)
        if row["version"] != expected_version or current["token"] != expected_token:
            raise LearningConflict("Stored matches changed; preview again before reprocessing")
        count = 0
        for mail in matching(db, json.loads(row["definition_json"])):
            if mail["corrected_category"]:
                continue
            p = rule_prediction(row, mail)
            db.execute(
                "UPDATE triage SET category=?,rule_id=?,reason=?,source_quote=? WHERE message_id=?",
                (p.category, p.rule_id, p.reason, p.source_quote, mail["id"]),
            )
            use(db, row, mail)
            count += 1
    return {"reprocessed": count}


def suggest_preference(db, effect):
    if not isinstance(effect, str) or effect not in EFFECTS:
        raise ValueError("Supported ranking preference required")
    db.execute("BEGIN IMMEDIATE")
    with db:
        result = save(
            db,
            "preference",
            {"effect": effect},
            source="private",
            origin_type="structured_preference",
        )
    return result


def instruction(db, text):
    if not isinstance(text, str) or len(text) > 300:
        raise ValueError("A supported explicit instruction is required")
    normal = text.strip().casefold().rstrip(".")
    found = re.fullmatch(
        r"(?:remember(?: that)?(?: i)?|always) "
        r"(?:prefer (remote roles|hybrid roles|in[ -]person roles)|avoid (relocation))",
        normal,
    )
    if not found:
        raise ValueError(
            "Supported: always prefer remote, hybrid, in-person roles; avoid relocation"
        )
    effect = {
        "remote roles": "prefer_remote",
        "hybrid roles": "prefer_hybrid",
        "in-person roles": "prefer_in_person",
        "in person roles": "prefer_in_person",
        "relocation": "avoid_relocation",
    }[found[1] or found[2]]
    db.execute("BEGIN IMMEDIATE")
    with db:
        definition = {"effect": effect}
        existing = db.execute(
            "SELECT id FROM learned_rules WHERE kind=? AND definition_json=? "
            "AND status IN ('suggested','active')",
            ("preference", json.dumps(definition, sort_keys=True)),
        ).fetchone()
        rule = save(
            db,
            "preference",
            definition,
            source="private",
            origin_type="explicit_instruction",
            status="active",
        )
        if existing:
            row = get(db, rule["id"])
            version, now = row["version"] + 1, timestamp()
            db.execute(
                "UPDATE learned_rules SET status='active',version=?,changed_at=?,"
                "source='private',origin_type='explicit_instruction' WHERE id=?",
                (version, now, row["id"]),
            )
            db.execute(
                "INSERT INTO learned_rule_versions VALUES (?,?,?,?,?)",
                (row["id"], version, "active", row["definition_json"], now),
            )
            emit(
                db,
                Kind.RULE_ACTIVATED,
                Empty(),
                entity_type="rule",
                entity_id=row["id"],
                revision_id=version,
            )
            rule = public(db, get(db, row["id"]))
        preferences.record_uses(db)
        rule = public(db, get(db, rule["id"]))
    return rule


def skip_suggestion(db, oid, reason):
    normal = reason.strip().casefold().rstrip(".")
    effects = {
        "requires relocation": "avoid_relocation",
        "relocation required": "avoid_relocation",
        "prefer remote roles": "prefer_remote",
        "prefer hybrid roles": "prefer_hybrid",
    }
    if normal not in effects:
        return None  # Arbitrary prose never becomes an executable rule.
    return save(
        db,
        "preference",
        {"effect": effects[normal]},
        source=provenance(db, "opportunity", oid),
        origin_type="opportunity",
        origin_id=oid,
    )


def review(db, *, replay=False):
    rows = db.execute(
        "SELECT m.*,COALESCE(t.corrected_category,t.category) AS effective "
        "FROM messages m LEFT JOIN triage t ON t.message_id=m.id ORDER BY m.id"
    ).fetchall()
    rows = [r for r in rows if not replay or r["source"] == "synthetic"]
    groups = {}
    for row in rows:
        if row["effective"] != "needs_review":
            continue
        address = mailbox(row["sender"])
        key = address or f"Unparseable sender {row['id']}"
        group = groups.setdefault(
            key, {"mailbox": address, "count": 0, "examples": [], "mixed": False}
        )
        group["count"] += 1
        represented = {normalize_subject(e["subject"]).casefold() for e in group["examples"]}
        if len(group["examples"]) < 5 and normalize_subject(row["subject"]).casefold() not in represented:
            group["examples"].append({"message_id": row["id"], "subject": row["subject"]})
    for group in groups.values():
        group["mixed"] = (
            len(
                {
                    normalize_subject(r["subject"]).casefold()
                    for r in rows
                    if mailbox(r["sender"]) == group["mailbox"]
                }
            )
            > 1
        )
    return {
        "unresolved_total": sum(g["count"] for g in groups.values()),
        "stored_total": len(rows),
        "groups": sorted(groups.values(), key=lambda g: (-g["count"], g["mailbox"] or "")),
    }
