"""Explicit two-step JD recovery, confined bytes and append-only extraction history."""

import hashlib
import json
from pathlib import Path

from inbound.extract.attachments import DOCX, parse_bytes
from inbound.extract.call import safe_lines
from inbound.extract.pipeline import (
    invalidate_reviewed_packs,
    latest_revision,
    reextract_message,
)
from inbound.extract.roles import parse_roles
from inbound.ledger import timestamp
from inbound.pause import check
from inbound.provenance import locations
from inbound.sources.base import MAX_BYTES, safe_attachment_path


class RecoveryConflict(RuntimeError):
    """A preview, call or active job no longer permits this write."""


class TooLarge(ValueError):
    """The document exceeds the 10 MB bound."""


def guard(db, opportunity_id, mode):
    if mode != "local":
        raise ValueError("Attachment recovery is available in local mode")
    check(db)
    if db.execute(
        "SELECT 1 FROM runs WHERE status='running' AND "
        "(operation_key='import' OR operation_key=?)", (f"pack:{opportunity_id}",),
    ).fetchone():
        raise RecoveryConflict("Work is running; wait before attaching the JD")


def target(db, opportunity_id, attachment_id):
    row = db.execute(
        "SELECT a.*,r.id AS revision_id,r.opportunity_id,m.subject,m.provider_id "
        "FROM attachments a JOIN opportunity_revisions r ON r.message_id=a.message_id "
        "JOIN messages m ON m.id=a.message_id WHERE r.opportunity_id=? AND a.id=?",
        (opportunity_id, attachment_id),
    ).fetchone()
    if row is None:
        raise LookupError("Attachment not found on this call")
    return row


def read_document(settings, *, path=None, payload=None, filename=None, mime=None):
    if (path is None) == (payload is None):
        raise ValueError("Supply one local path or one upload")
    if path is not None:
        root = settings.data_root.resolve()
        candidate = Path(path)
        candidate = (candidate if candidate.is_absolute() else root / candidate).resolve()
        if not candidate.is_relative_to(root):
            raise ValueError("File must resolve under the configured data root")
        filename = candidate.name
        with candidate.open("rb") as stream:
            payload = stream.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise TooLarge("Attachment size cap exceeded (10 MB)")
    if not isinstance(filename, str) or "/" in filename or "\\" in filename:
        raise ValueError("A plain original filename is required")
    safe_attachment_path(settings.data_root, filename)
    expected = {".pdf": "application/pdf", ".docx": DOCX}.get(Path(filename).suffix.lower())
    if expected is None or (mime is not None and mime != expected):
        raise ValueError("File extension and MIME must identify a PDF or DOCX")
    magic = b"%PDF-" if expected == "application/pdf" else b"PK\x03\x04"
    if not payload.startswith(magic):
        raise ValueError("File magic does not match its PDF/DOCX type")
    return payload, filename, expected


def metadata(db, opportunity_id, attachment_id, payload, filename, mime):
    row = target(db, opportunity_id, attachment_id)
    op = db.execute("SELECT * FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
    previous = db.execute(
        "SELECT 1 FROM attachment_recoveries WHERE attachment_id=? AND sha256=?",
        (attachment_id, hashlib.sha256(payload).hexdigest()),
    ).fetchone()
    if not previous and (
        not op["blocked_reason"] or row["parse_status"] not in {"missing", "unreadable"}
    ):
        raise RecoveryConflict("Select a missing or unreadable attachment on a blocked call")
    parsed = parse_bytes(payload, mime)
    return {
        **parsed,
        "attachment_id": attachment_id,
        "original_filename": filename,
        "mime": mime,
        "content_hash": hashlib.sha256(payload).hexdigest(),
        "expected_revision_id": latest_revision(db, opportunity_id)["id"],
        "expected_content_version": op["content_version"],
        "roles": parse_roles(safe_lines(parsed["text"]), row["subject"], row["provider_id"]
                             )["normalized"] or [],
    }


def preview(db, settings, opportunity_id, attachment_id, *, mode="local", **document):
    guard(db, opportunity_id, mode)
    payload, filename, mime = read_document(settings, **document)
    result = metadata(db, opportunity_id, attachment_id, payload, filename, mime)
    check(db)
    return result


def public_record(row):
    return {k: row[k] for k in (
        "id", "attachment_id", "message_id", "revision_id", "sha256", "original_filename",
        "mime", "supplier", "recorded_at", "parse_status", "reason", "content_version",
    )}


def confirm(db, settings, opportunity_id, attachment_id, *, content_hash, expected_revision_id,
            expected_content_version, mode="local", **document):
    guard(db, opportunity_id, mode)
    if type(expected_revision_id) is not int or type(expected_content_version) is not int:
        raise ValueError("Preview revision and content version required")
    payload, filename, mime = read_document(settings, **document)
    if content_hash != hashlib.sha256(payload).hexdigest():
        raise RecoveryConflict("File differs from the preview; preview it again")
    db.execute("BEGIN IMMEDIATE")
    with db:
        guard(db, opportunity_id, mode)
        row = target(db, opportunity_id, attachment_id)
        op = db.execute("SELECT * FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
        if latest_revision(db, opportunity_id)["id"] != expected_revision_id:
            raise RecoveryConflict("This call changed; reload and preview again")
        previous = db.execute(
            "SELECT * FROM attachment_recoveries WHERE attachment_id=? AND sha256=?",
            (attachment_id, content_hash),
        ).fetchone()
        if previous:
            if (op["content_version"] == previous["content_version"] + 1
                and expected_content_version in {previous["content_version"], op["content_version"]}
                and previous["original_filename"] == filename and previous["mime"] == mime):
                return public_record(previous)
            raise RecoveryConflict("This call changed after recovery; reload before continuing")
        if op["content_version"] != expected_content_version:
            raise RecoveryConflict("Call content changed; reload and preview again")
        result = metadata(db, opportunity_id, attachment_id, payload, filename, mime)
        history = {
            "attachment": dict(row),
            "extraction": dict(db.execute(
                "SELECT * FROM message_extractions WHERE message_id=?", (row["message_id"],)
            ).fetchone()),
            "revisions": [dict(r) for r in db.execute(
                "SELECT * FROM opportunity_revisions WHERE opportunity_id=?", (opportunity_id,))],
        }
        relative = f"recovered/{opportunity_id}/{attachment_id}/{content_hash}{Path(filename).suffix}"
        destination = safe_attachment_path(settings.data_root, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = safe_attachment_path(settings.data_root, relative)
        if destination.exists():
            with destination.open("rb") as stream:
                if stream.read(MAX_BYTES + 1) != payload:
                    raise RecoveryConflict("Stored bytes do not match the supplied document")
        else:
            with destination.open("xb") as stream:
                stream.write(payload)
        check(db)
        db.execute(
            "UPDATE attachments SET mime=?,bytes_path=?,import_root=?,content_base64=NULL,"
            "bytes_available=1 WHERE id=?",
            (mime, relative, str(settings.data_root.resolve()), attachment_id),
        )
        reextract_message(db, row["message_id"])
        db.execute("DELETE FROM attachment_locations WHERE attachment_id=?", (attachment_id,))
        if result["parse_status"] == "parsed":
            from inbound.models import Attachment

            declaration = Attachment(row["filename"], mime, relative, True, "parsed",
                                     str(settings.data_root.resolve()))
            db.execute("INSERT INTO attachment_locations VALUES (?,?)",
                       (attachment_id, json.dumps(locations(declaration))))
        invalidate_reviewed_packs(db, opportunity_id)
        status = op["status"] if op["status"] in {"skipped", "submitted_by_me"} else (
            "blocked" if db.execute("SELECT blocked_reason FROM opportunities WHERE id=?",
                                    (opportunity_id,)).fetchone()[0] else "needs_review")
        db.execute(
            "UPDATE opportunities SET content_version=content_version+1,status=?,updated_at=? "
            "WHERE id=?", (status, timestamp(), opportunity_id),
        )
        cursor = db.execute(
            "INSERT INTO attachment_recoveries(opportunity_id,attachment_id,message_id,revision_id,"
            "expected_revision_id,content_version,sha256,original_filename,mime,supplier,recorded_at,"
            "stored_path,parse_status,reason,previous_state_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,'uzair',?,?,?,?,?)",
            (opportunity_id, attachment_id, row["message_id"], row["revision_id"],
             expected_revision_id, expected_content_version, content_hash, filename, mime,
             timestamp(), relative, result["parse_status"], result["reason"], json.dumps(history)),
        )
        db.execute(
            "INSERT INTO review_events(opportunity_id,revision_id,action,created_at,details_json) "
            "VALUES (?,?,'attachment_recovered',?,?)",
            (opportunity_id, row["revision_id"], timestamp(), json.dumps({
                "recovery_id": cursor.lastrowid, "attachment_id": attachment_id,
                "sha256": content_hash, "parse_status": result["parse_status"],
                "content_version": expected_content_version + 1,
            })),
        )
        check(db)
        return public_record(db.execute("SELECT * FROM attachment_recoveries WHERE id=?",
                                        (cursor.lastrowid,)).fetchone())
