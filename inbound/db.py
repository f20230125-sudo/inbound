"""Forward-only SQLite migrations and atomic, append-only import history."""

import hashlib
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from inbound.ledger import timestamp
from inbound.pause import check


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, sha256 TEXT NOT NULL)"
    )
    for migration in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
        sql = migration.read_text(encoding="utf-8")
        digest = hashlib.sha256(sql.encode()).hexdigest()
        applied = db.execute(
            "SELECT sha256 FROM schema_migrations WHERE name=?", (migration.name,)
        ).fetchone()
        if applied:
            if applied[0] != digest:
                db.close()
                raise ValueError("Applied migration was modified")
            continue
        try:
            db.executescript("BEGIN;\n" + sql)
            db.execute("INSERT INTO schema_migrations VALUES (?,?)", (migration.name, digest))
            db.commit()
        except Exception:
            db.rollback()
            db.close()
            raise
    return db


def import_messages(db, messages):
    check(db)
    # Parse/validate the entire batch before opening the write transaction.
    staged = []
    sources = set()
    for message in messages:
        check(db)
        if message.source not in {"private", "synthetic"}:
            raise ValueError("Unknown import provenance")
        sources.add(message.source)
        if len(sources) > 1:
            raise ValueError("Mixed import provenance")
        staged.append(message)
    check(db)
    counts = {"imported": 0, "unchanged": 0, "changed": 0}
    with db:
        for message in sorted(staged, key=lambda m: (m.sent_at, m.provider, m.provider_id)):
            check(db)
            digest = message.content_hash
            row = db.execute(
                "SELECT id FROM messages WHERE provider=? AND provider_id=?",
                (message.provider, message.provider_id),
            ).fetchone()
            if row:
                message_id = row[0]
                known = db.execute(
                    "SELECT 1 FROM message_history WHERE message_id=? AND content_hash=?",
                    (message_id, digest),
                ).fetchone()
                if known:
                    counts["unchanged"] += 1
                    continue
                counts["changed"] += 1
            else:
                cursor = db.execute(
                    "INSERT INTO messages(provider,provider_id,thread_id,sent_at,received_at,"
                    'sender,"to",cc,bcc,subject,body_text,attachments_json,labels,body_exported,'
                    "body_complete,source,content_hash,imported_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        message.provider,
                        message.provider_id,
                        message.thread_id,
                        message.sent_at.isoformat(),
                        message.received_at.isoformat(),
                        message.sender,
                        message.to,
                        message.cc,
                        message.bcc,
                        message.subject,
                        message.body_text,
                        json.dumps([asdict(a) for a in message.attachments], ensure_ascii=False),
                        message.labels,
                        message.body_exported,
                        int(message.body_complete),
                        message.source,
                        digest,
                        timestamp(),
                    ),
                )
                message_id = cursor.lastrowid
                for a in message.attachments:
                    db.execute(
                        "INSERT INTO attachments(message_id,filename,mime,bytes_path,"
                        "bytes_available,parse_status) VALUES (?,?,?,?,?,?)",
                        (
                            message_id,
                            a.name,
                            a.mime,
                            a.bytes_path,
                            int(a.bytes_available),
                            a.parse_status,
                        ),
                    )
                counts["imported"] += 1
            db.execute(
                "INSERT INTO message_history(message_id,content_hash,snapshot_json,"
                "imported_at) VALUES (?,?,?,?)",
                (
                    message_id,
                    digest,
                    json.dumps(message.canonical(), ensure_ascii=False, sort_keys=True),
                    timestamp(),
                ),
            )
    return counts
