"""Private, versioned memory projection. Prose is retrieval context, never CV evidence/rules."""

import json
import os
import re
import sqlite3
import threading
from contextlib import closing
from uuid import uuid4

import yaml

from inbound import memory_files as files
from inbound.db import connect
from inbound.ledger import timestamp
from inbound.pause import PausedError, check, is_paused
from inbound.steps import Kind, MemoryPublication, emit


class MemoryConflict(RuntimeError):
    pass


def current_snapshot(db):
    return db.execute("SELECT * FROM memory_snapshots ORDER BY version DESC LIMIT 1").fetchone()


def guard(db, expected_generation=None):
    check(db)
    if db.execute(
        "SELECT 1 FROM runs WHERE status='running' AND operation_key='import'"
    ).fetchone():
        raise MemoryConflict("Import is running; refresh memory after publication")
    if expected_generation is not None and db.execute(
        'SELECT generation FROM domain_generation WHERE id=1'
    ).fetchone()[0] != expected_generation:
        raise MemoryConflict('Stored information changed; ask again before confirming')


def readable_title(document):
    if document.get('title'):
        return document['title']
    description = document.get('description', '').strip()
    if description:
        return re.split(r'[.;!\n]|,\s', description, maxsplit=1)[0].strip() or description
    return document['name'].replace('-', ' ').replace('_', ' ').capitalize()


def project(row):
    doc = json.loads(row["document_json"])
    return (
        doc
        | {
            k: row[k]
            for k in (
                "id",
                "origin",
                "source",
                "file",
                "status",
                "created_at",
                "changed_at",
                "version",
                "local_file",
            )
        }
        | {
            "display_title": readable_title(doc),
            "influence": "remembered",
            "scope": "Local retrieval only; no active behavior rule",
            "conflicts": json.loads(row["conflicts_json"]),
            "source_content": json.loads(row["source_json"]) if row["source_json"] else None,
            "citation": {
                "entity_type": "memory",
                "entity_id": row["id"],
                "version": row["version"],
            },
        }
    )


def view(db, *, replay=False):
    snapshot = current_snapshot(db)
    items = [
        project(r)
        for r in db.execute(
            "SELECT * FROM memories WHERE status IN ('remembered','disabled') AND document_json IS NOT NULL"
            + (" AND source='synthetic'" if replay else "")
            + " ORDER BY created_at,id"
        )
    ]
    return {
        "version": snapshot["version"] if snapshot else 0,
        "published_at": snapshot["published_at"] if snapshot else None,
        "items": items,
        "published": False,
        "error": db.execute("SELECT error FROM memory_scan_state WHERE id=1").fetchone()[0],
    }


def retrieve(db, *, replay=False):
    # All active retrieval goes through this filter; no content cache survives forgetting.
    return [i for i in view(db, replay=replay)["items"] if i["status"] == "remembered"]


def resolve(db, reference, *, replay=False):
    from inbound.steps import identifier

    if (
        not isinstance(reference, dict)
        or set(reference) != {"entity_type", "entity_id", "version"}
        or reference["entity_type"] != "memory"
        or not identifier(reference["entity_id"])
        or type(reference["version"]) is not int
        or reference["version"] < 1
    ):
        raise ValueError("Typed, versioned memory reference required")
    row = db.execute("SELECT * FROM memories WHERE id=?", (reference["entity_id"],)).fetchone()
    if row is None or row["status"] != "remembered" or (replay and row["source"] != "synthetic"):
        return None
    revision = db.execute(
        "SELECT record_json FROM memory_revisions WHERE memory_id=? AND version=?",
        (row["id"], reference["version"]),
    ).fetchone()
    if not revision or not revision[0]:
        return None
    return json.loads(revision[0]) | {
        "newer_version": row["version"] if row["version"] > reference["version"] else None
    }


def read_snapshot(db, settings):
    last = current_snapshot(db)
    return files.scan(settings, json.loads(last["roots_json"]) if last else ())


def fingerprint(documents, roots):
    return files.digest([documents, roots])


def publish(db, documents, roots, *, source, force=False):
    last = current_snapshot(db)
    stamp = fingerprint(documents, roots)
    db.execute("UPDATE memory_scan_state SET error=NULL WHERE id=1")
    if not force and ((last and last["fingerprint"] == stamp) or (not last and not documents)):
        return False
    now = timestamp()
    version = db.execute(
        "INSERT INTO memory_snapshots(published_at,fingerprint,roots_json) VALUES (?,?,?)",
        (now, stamp, json.dumps(roots)),
    ).lastrowid
    existing = {r["identity"]: dict(r) for r in db.execute("SELECT * FROM memories")}
    suppressed = {r[0] for r in db.execute("SELECT identity FROM memory_suppressions")}
    overrides = {r["local_file"]: r for r in existing.values() if r["local_file"]}
    by_file = {d["file"]: d for d in documents}
    updated = {}
    for entry in documents:
        if entry["file"] in overrides:
            continue
        identity = entry["identity"]
        prior = existing.get(identity)
        if identity in suppressed:
            continue
        row = (
            prior.copy()
            if prior
            else {
                "id": uuid4().hex,
                "identity": identity,
                "origin": entry["origin"],
                "source": source if entry["origin"] == "imported" else "private",
                "local_file": None,
                "base_hash": None,
                "disabled": 0,
                "created_at": now,
            }
        )
        # Private provenance is sticky even when a scanner is misconfigured later.
        if source == "private":
            row["source"] = "private"
        local = by_file.get(row["local_file"])
        if row["local_file"] and local is None:
            raise ValueError("Local override missing; snapshot is incomplete")
        conflicts = []
        if local and row["base_hash"] != entry["hash"]:
            conflicts.append("Curated source changed after your local edit; review both versions.")
        row.update(
            file=entry["file"],
            document_json=json.dumps(local["document"] if local else entry["document"]),
            source_json=json.dumps(entry["document"]) if local else None,
            source_hash=entry["hash"],
            status="disabled" if row["disabled"] else "remembered",
            conflicts_json=json.dumps(conflicts),
        )
        updated[identity] = row
    # A deleted curated entry cannot leave a local override silently active.
    for identity, row in existing.items():
        if identity not in updated:
            row = row.copy()
            row.update(
                status="forgotten" if identity in suppressed else "deleted",
                document_json=None,
                source_json=None,
                conflicts_json="[]",
            )
            updated[identity] = row
    names = {}
    for row in updated.values():
        if row["status"] == "remembered":
            doc = json.loads(row["document_json"])
            names.setdefault(doc["name"].casefold(), []).append(row)
    for group in names.values():
        if len({r["document_json"] for r in group}) > 1:
            for row in group:
                row["conflicts_json"] = json.dumps(
                    json.loads(row["conflicts_json"])
                    + [
                        "Another enabled memory with this name disagrees. Neither overrides source evidence."
                    ]
                )
    changed = 0
    for identity, row in updated.items():
        prior = existing.get(identity)
        comparable = (
            "file",
            "document_json",
            "source_json",
            "source_hash",
            "status",
            "conflicts_json",
            "disabled",
            "local_file",
            "base_hash",
            "source",
        )
        if prior and all(row.get(k) == prior.get(k) for k in comparable):
            continue
        changed += 1
        row.update(changed_at=now, version=version)
        columns = tuple(row)
        db.execute(
            "INSERT INTO memories("
            + ",".join(columns)
            + ") VALUES ("
            + ",".join("?" for _ in columns)
            + ") ON CONFLICT(id) DO UPDATE SET "
            + ",".join(f"{c}=excluded.{c}" for c in columns if c != "id"),
            tuple(row[c] for c in columns),
        )
        db.execute(
            "INSERT INTO memory_revisions VALUES (?,?,?)",
            (row["id"], version, json.dumps(project(row)) if row["document_json"] else None),
        )
    event_source = "private" if any(r["source"] == "private" for r in updated.values()) else source
    emit(
        db,
        Kind.MEMORY_PUBLISHED,
        MemoryPublication(changed),
        entity_type="memory_snapshot",
        entity_id=version,
        snapshot_version=version,
        source=event_source,
        dedupe_key=f"memory:{version}:published",
    )
    return True


def refresh(db, settings, *, source="private"):
    if source not in {"private", "synthetic"}:
        raise ValueError("Unknown memory provenance")
    db.execute("BEGIN IMMEDIATE")
    with db:
        guard(db)
        try:
            documents, roots = read_snapshot(db, settings)
            # Detect missing local overrides before writing anything.
            present = {d["file"] for d in documents}
            if any(
                r[0] not in present
                for r in db.execute(
                    "SELECT local_file FROM memories WHERE local_file IS NOT NULL "
                    "AND status NOT IN ('forgotten','deleted')"
                )
            ):
                raise ValueError("Local override missing")
        except OSError, ValueError, yaml.YAMLError:
            db.execute("UPDATE memory_scan_state SET error='invalid_snapshot' WHERE id=1")
            published = False
        else:
            published = publish(db, documents, roots, source=source)
    return view(db) | {"published": published}


def replace_file(root, name, payload):
    """Only generated filenames are accepted by callers; root stays pinned during writes."""
    target = root / name
    if (target.exists() or target.is_symlink()) and (files.is_link(target) or not target.is_file()):
        raise ValueError("Unsafe local memory file")
    temporary = root / (uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def mutate(db, settings, action, *, expected_version, memory_id=None, document=None,
           expected_generation=None):
    from inbound.steps import identifier

    if not isinstance(action, str) or action not in {"add", "edit", "forget", "disable", "enable"}:
        raise ValueError("Unsupported memory action")
    if type(expected_version) is not int or expected_version < 0:
        raise ValueError("Current memory version required")
    if action != "add" and (not isinstance(memory_id, str) or not identifier(memory_id)):
        raise ValueError("Opaque memory ID required")
    if action in {"add", "edit"}:
        files.validate(document)
    db.execute("BEGIN IMMEDIATE")
    local_path, previous_bytes, touched = None, None, False
    try:
        guard(db, expected_generation)
        last = current_snapshot(db)
        if (last["version"] if last else 0) != expected_version:
            raise MemoryConflict("Memory changed; refresh before saving")
        documents, roots = read_snapshot(db, settings)
        if last and last["fingerprint"] != fingerprint(documents, roots):
            raise MemoryConflict("Snapshot files changed; refresh before saving")
        row = db.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        if action != "add" and (row is None or row["status"] not in {"remembered", "disabled"}):
            raise MemoryConflict("Memory is no longer available")
        # Pin both the configured data root and the local directory against replacement.
        with (
            files.pinned_directory(settings.data_root),
            files.pinned_directory(settings.data_root / "memory-local", create=True),
        ):
            root = settings.data_root / "memory-local"
            if action in {"add", "edit"}:
                if action == "add":
                    name, source_id = uuid4().hex + ".md", uuid4().hex
                elif row["origin"] == "local":
                    name = row["file"].split("/")[1]
                    source_id = next(d["source_id"] for d in documents if d["file"] == row["file"])
                else:
                    name, source_id = row["id"] + ".md", row["id"]
                local_path = root / name
                if local_path.exists():
                    previous_bytes = files.read_file(local_path, root)
                payload = files.encode(document, source_id)
                replace_file(root, name, payload)
                touched = True
                if action == "edit" and row["origin"] == "imported":
                    db.execute(
                        "UPDATE memories SET local_file=?,base_hash=?,source='private' WHERE id=?",
                        (f"memory-local/{name}", row["source_hash"], memory_id),
                    )
            elif action == "forget":
                if row["origin"] == "imported":
                    db.execute(
                        "INSERT OR IGNORE INTO memory_suppressions VALUES (?,?,?)",
                        (row["identity"], memory_id, timestamp()),
                    )
                name = row["local_file"] or (row["file"] if row["origin"] == "local" else None)
                if name:
                    local_path = root / name.split("/")[1]
                    previous_bytes = files.read_file(local_path, root)
                    local_path.unlink()
                    touched = True
                db.execute(
                    "UPDATE memories SET local_file=NULL,base_hash=NULL WHERE id=?", (memory_id,)
                )
                # Preserve opaque historical references, remove content from derived history.
                db.execute(
                    "UPDATE memory_revisions SET record_json=NULL WHERE memory_id=?", (memory_id,)
                )
            else:
                db.execute(
                    "UPDATE memories SET disabled=? WHERE id=?",
                    (int(action == "disable"), memory_id),
                )
            documents, roots = read_snapshot(db, settings)
            publish(db, documents, roots, source="private", force=True)
            if memory_id:
                emit(
                    db,
                    Kind.MEMORY_CHANGED,
                    MemoryPublication(1),
                    entity_type="memory",
                    entity_id=memory_id,
                    source="private",
                )
            db.commit()
    except BaseException:
        db.rollback()
        if touched and local_path:
            with files.pinned_directory(local_path.parent):
                if previous_bytes is None:
                    local_path.unlink(missing_ok=True)
                else:
                    replace_file(local_path.parent, local_path.name, previous_bytes)
        raise
    return view(db) | {"published": True}


class Poller:
    """A local-only bounded scan once per minute, started by serve; never by a GET."""

    def __init__(self, settings, *, source="private"):
        self.settings, self.source = settings, source
        self.stop = threading.Event()

    def tick(self):
        try:
            with closing(connect(self.settings.db_path)) as db:
                if (
                    is_paused(db)
                    or db.execute(
                        "SELECT 1 FROM runs WHERE status='running' AND operation_key='import'"
                    ).fetchone()
                ):
                    return None
                return refresh(db, self.settings, source=self.source)
        except MemoryConflict, PausedError, sqlite3.Error, OSError:
            return None  # retry on the next scheduled scan; never publish a partial snapshot

    def run(self):
        while not self.stop.is_set():
            self.tick()
            self.stop.wait(60)

    def start(self):
        threading.Thread(target=self.run, name="memory-poller", daemon=True).start()
        return self
