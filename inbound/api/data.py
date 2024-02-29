"""JSON projections: source provenance, evidence and confined artifact access."""

import json
import re
from pathlib import Path

from flask import abort

from inbound.evidence.registry import load_registry
from inbound.extract.call import safe_lines
from inbound.extract.pipeline import opportunity_state
from inbound.packs.answers import answers
from inbound.packs.rank import rank


def clean_replay(value):
    if isinstance(value, dict):
        return {
            k: clean_replay(v)
            for k, v in value.items()
            if k not in {"import_root", "bytes_path", "content_base64", "files_json"}
        }
    if isinstance(value, list):
        return [clean_replay(v) for v in value]
    if isinstance(value, str):
        lines = safe_lines(value).splitlines()
        return "\n".join(
            line
            for line in lines
            if not re.search(
                r"SYNTHETIC-CANARY|api[_-]?key|secret|[A-Za-z]:[\\/]|"
                r"(?:^|[\\/\s])private[\\/]|collector\.demo",
                line,
                re.IGNORECASE,
            )
        )
    return value


def messages(db, category=None):
    result = []
    for row in db.execute(
        "SELECT m.id,m.provider_id,m.subject,m.sender,m.sent_at,m.received_at,m.body_text,"
        "m.body_complete,m.source,t.category AS original_category,t.corrected_category,"
        "t.reason,t.rule_id,t.source_quote,t.urgency,t.corrected_at,e.fields_json,"
        "r.opportunity_id FROM messages m LEFT JOIN triage t ON t.message_id=m.id "
        "LEFT JOIN message_extractions e ON e.message_id=m.id "
        "LEFT JOIN opportunity_revisions r ON r.message_id=m.id "
        "ORDER BY julianday(m.received_at) DESC,m.id"
    ):
        item = dict(row)
        item["category"] = row["corrected_category"] or row["original_category"]
        if category and item["category"] != category:
            continue
        item["fields"] = json.loads(item.pop("fields_json") or "{}")
        item["classification_history"] = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM category_history WHERE message_id=? ORDER BY id", (row["id"],)
            )
        ]
        item["attachment_count"] = db.execute(
            "SELECT count(*) FROM attachments WHERE message_id=?", (row["id"],)
        ).fetchone()[0]
        result.append(item)
    return result


def enrich(value, sources, current_id):
    if isinstance(value, list):
        return [enrich(v, sources, current_id) for v in value]
    if not isinstance(value, dict):
        return value
    item = {k: enrich(v, sources, current_id) for k, v in value.items()}
    if "value" in item and "message_id" in item and "source_text" in item:
        item["provenance"] = {k: item[k] for k in ("message_id", "source", "source_text")}
    origin = item.get("provenance")
    if origin:
        message = sources.get(origin.get("message_id"))
        if message:
            origin.update(sent_at=message["sent_at"], revision_id=message["revision_id"])
            location = origin.get("source", "body")
            if location == "message":
                location = (
                    "subject"
                    if item.get("source_text") and item["source_text"] in message["subject"]
                    else "body"
                )
            origin["location"] = origin.get("location", location)
            if item.get("status") == "unknown" and item.get("missing_reason") == "Not stated":
                item["missing_reason"] = (
                    "Not stated in the complete message"
                    if message["body_complete"]
                    else "Exported body is incomplete"
                )
            if location == "attachment":
                quote = item.get("source_text") or origin.get("source_text") or ""
                origin["locations"] = matching_locations(message, origin.get("name"), quote)
            item["inherited"] = message["revision_id"] != current_id
    if item.get("name") == "roles" and item.get("normalized"):
        for role in item["normalized"]:
            for requirement in role.get("requirements") or []:
                text = requirement["text"]
                quote = text if text in item["source_text"] else item["source_text"]
                requirement["source_text"] = quote
                requirement["provenance"] = dict(origin or {})
                if origin and origin.get("source") == "attachment":
                    message = sources.get(origin.get("message_id"), {})
                    requirement["provenance"]["locations"] = matching_locations(
                        message, origin.get("name"), quote
                    )
    return item


def matching_locations(message, name, quote):
    return [
        location
        for location in message.get("attachment_locations", {}).get(name, [])
        if quote
        and location["source_text"]
        and (quote in location["source_text"] or location["source_text"] in quote)
    ]


def opportunity(db, oid, *, clock=None, demo=False):
    if not db.execute("SELECT 1 FROM opportunities WHERE id=?", (oid,)).fetchone():
        abort(404)
    state = opportunity_state(db, oid, clock=clock)
    revisions = []
    sources = {}
    for row in db.execute(
        "SELECT r.*,m.provider_id,m.sent_at,m.received_at,m.subject,m.body_text,m.source,m.body_complete "
        "FROM opportunity_revisions r JOIN messages m ON m.id=r.message_id "
        "WHERE r.opportunity_id=? ORDER BY julianday(m.sent_at),m.id",
        (oid,),
    ):
        item = dict(row)
        item["fields"] = json.loads(item.pop("fields_json"))
        item["local_fields"] = json.loads(item.pop("local_fields_json"))
        revisions.append(item)
        sources[row["provider_id"]] = {**item, "revision_id": row["id"]}
        sources[row["provider_id"]]["attachment_locations"] = {
            a["filename"]: json.loads(a["locations_json"])
            for a in db.execute(
                "SELECT a.filename,l.locations_json FROM attachments a "
                "JOIN attachment_locations l ON l.attachment_id=a.id WHERE a.message_id=?",
                (row["message_id"],),
            )
        }
    for revision in revisions:
        revision["fields"] = enrich(revision["fields"], sources, state["revision_id"])
        revision["local_fields"] = enrich(revision["local_fields"], sources, revision["id"])
    state["revisions"] = revisions
    state["fields"] = enrich(state["fields"], sources, state["revision_id"])
    state["attachments"] = [
        dict(row)
        for row in db.execute(
            "SELECT a.id,a.message_id,a.filename,a.mime,a.bytes_available,a.parse_status,a.text,"
            "m.provider_id,m.sent_at,r.id AS revision_id FROM attachments a "
            "JOIN messages m ON m.id=a.message_id JOIN opportunity_revisions r ON r.message_id=m.id "
            "WHERE r.opportunity_id=? ORDER BY a.id",
            (oid,),
        )
    ]
    for attachment in state["attachments"]:
        attachment["locations"] = sources[attachment["provider_id"]]["attachment_locations"].get(
            attachment["filename"], []
        )
        attachment["purpose"] = "brochure" if "brochure" in attachment["filename"].lower() else "JD"
    state["merge_suggestions"] = [
        dict(r)
        for r in db.execute("SELECT * FROM merge_suggestions WHERE opportunity_id=?", (oid,))
    ]
    state["packs"] = [
        dict(r)
        for r in db.execute(
            "SELECT id,revision_id,status,created_at,provisional FROM packs "
            "WHERE opportunity_id=? ORDER BY created_at DESC,id DESC",
            (oid,),
        )
    ]
    state["review_history"] = history(db, oid)
    try:
        registry = load_registry(db, "demo" if demo else "public")
    except ValueError:
        registry = None
    roles = []
    for row in db.execute(
        "SELECT * FROM roles WHERE revision_id=? ORDER BY id", (state["revision_id"],)
    ):
        item = dict(row)
        item["requirements"] = json.loads(item.pop("requirements_json"))
        item["source_record"] = enrich(
            json.loads(item.pop("source_record_json")), sources, state["revision_id"]
        )
        normalized_roles = item["source_record"].get("normalized") or []
        matched_role = next(
            (role for role in normalized_roles if role["title"] == row["title"]), None
        )
        if matched_role:
            item["requirements"] = matched_role.get("requirements")
        item["coverage"] = rank(registry, item["requirements"]) if registry else None
        roles.append(item)
    recommended = (
        max(
            roles,
            key=lambda r: (
                r["coverage"]["coverage"]["ratio"]
                if r["coverage"] and r["coverage"]["coverage"]["ratio"] is not None
                else -1
            ),
        )
        if roles
        else None
    )
    state["recommended_role_id"] = recommended["id"] if recommended else None
    state["roles"] = roles
    state["evidence"] = registry
    return state


def history(db, oid):
    return [
        {**dict(r), "details": json.loads(r["details_json"])}
        for r in db.execute(
            "SELECT * FROM review_events WHERE opportunity_id=? ORDER BY id", (oid,)
        )
    ]


def pack_row(db, pid):
    row = db.execute("SELECT * FROM packs WHERE id=?", (pid,)).fetchone()
    if row is None:
        abort(404)
    return row


def artifact(row, settings):
    files = json.loads(row["files_json"])
    filename = files.get("pdf")
    if not filename:
        abort(404)
    path = Path(filename).resolve()
    allowed = (settings.data_root / "packs" / row["id"]).resolve()
    root = (settings.data_root / "packs").resolve()
    if (
        not root.is_relative_to(settings.data_root.resolve())
        or not allowed.is_relative_to(root)
        or not path.is_relative_to(allowed)
        or path.suffix.lower() != ".pdf"
        or not path.is_file()
    ):
        abort(404)
    return path


def pack_detail(db, pid, settings):
    row = pack_row(db, pid)
    path = artifact(row, settings)
    item = {
        k: row[k] for k in dict(row) if k not in {"files_json", "selection_json", "checks_json"}
    }
    selection = json.loads(row["selection_json"])
    item.update(
        selection=selection,
        checks=json.loads(row["checks_json"]),
        filename=path.name,
        pdf_url=f"/api/packs/{pid}/pdf",
        review_history=history(db, row["opportunity_id"]),
    )
    try:
        registry = load_registry(db, "demo" if row["demo"] else "public")
        item["answers"] = answers(registry, selection)
        projects = {p["id"]: p for p in registry["projects"]}
        for answer in item["answers"]:
            answer["character_counts"] = {
                k: len(answer[k]) for k in ("purpose", "technologies", "challenge_fix")
            }
            answer["answer_needed"] = [
                k for k in ("purpose", "challenge_fix") if answer[k].startswith("Uzair:")
            ]
            project = projects[answer["id"]]
            answer["provenance"] = {k: project.get(k) for k in ("id", "source_file", "source_hash")}
        item["evidence"] = registry
    except ValueError:
        item["answers"] = []
    return item


def runs(db):
    result = []
    for row in db.execute("SELECT * FROM runs ORDER BY julianday(started_at) DESC,id DESC"):
        item = dict(row)
        item["counts"] = json.loads(item.pop("counts_json"))
        item["status"] = "completed" if row["status"] == "success" else row["status"]
        item["execution"] = "offline deterministic"
        item["retry_history"] = []
        if row["finished_at"]:
            from datetime import datetime

            item["duration_seconds"] = (
                datetime.fromisoformat(row["finished_at"])
                - datetime.fromisoformat(row["started_at"])
            ).total_seconds()
        else:
            item["duration_seconds"] = None
        result.append(item)
    return result
