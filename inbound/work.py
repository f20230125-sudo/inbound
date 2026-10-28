"""Local jobs: persistent run IDs, stage boundaries and snapshot publication."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from inbound.db import connect, import_messages
from inbound.extract.pipeline import extract_messages
from inbound.ledger import timestamp
from inbound.pause import PausedError, check
from inbound.provenance import index_locations
from inbound.sources import eml_dir, export_txt, gmail_api
from inbound.steps import Empty, Kind, Snapshot, Stage, emit, scope
from inbound.triage.rules import triage_messages


def start_run(db, kind, *, opportunity_id=None, source_type=None, source_provenance=None):
    from inbound.extract.pipeline import latest_revision

    db.execute("BEGIN IMMEDIATE")
    with db:
        check(db)
        active = db.execute(
            "SELECT kind FROM runs WHERE status='running' AND operation_key IS NOT NULL"
        ).fetchall()
        if active and (kind == "import" or any(r["kind"] == "import" for r in active)):
            raise sqlite3.IntegrityError("Import and other writes must run separately")
        revision = latest_revision(db, opportunity_id) if opportunity_id is not None else None
        cursor = db.execute(
            "INSERT INTO runs(kind,started_at,status,operation_key,opportunity_id,source_type,"
            "stage,revision_id) VALUES (?,?,'running',?,?,?,'queued',?)",
            (
                kind,
                timestamp(),
                kind if kind == "import" else f"pack:{opportunity_id}",
                opportunity_id,
                source_type,
                revision["id"] if revision else None,
            ),
        )
        emit(
            db,
            Kind.IMPORT_STARTED if kind == "import" else Kind.PACK_QUEUED,
            Empty(),
            run_id=cursor.lastrowid,
            entity_type="opportunity" if opportunity_id else "run",
            entity_id=opportunity_id or cursor.lastrowid,
            source=source_provenance,
        )
    return cursor.lastrowid


def stage(db, run_id, name):
    check(db)
    db.execute("UPDATE runs SET stage=? WHERE id=?", (name, run_id))
    emit(
        db,
        Kind.IMPORT_STAGE,
        Stage(name),
        run_id=run_id,
        entity_type="run",
        entity_id=run_id,
        dedupe_key=f"run:{run_id}:stage:{name}",
    )
    db.commit()


def import_pipeline(
    db, run_id, root, source, provenance, *, clock=None, contacts=None, progress=None
):
    with scope(run_id=run_id, source=provenance):
        return _import_pipeline(
            db, run_id, root, source, provenance, clock=clock, contacts=contacts, progress=progress
        )


def _import_pipeline(
    db, run_id, root, source, provenance, *, clock=None, contacts=None, progress=None
):
    progress = progress or (lambda name: stage(db, run_id, name))
    progress("import")
    loader = {"export": export_txt.load, "eml": eml_dir.load, "gmail": gmail_api.load}.get(source)
    if loader is None:
        raise ValueError("Unknown source format")
    messages = list(loader(root, provenance))
    counts = import_messages(db, messages)
    counts["rejected"] = 0
    progress("triage")
    counts["triaged"] = triage_messages(db, personal_contacts=contacts)
    progress("extraction")
    counts.update(extract_messages(db, clock=clock))
    from inbound.learning_preferences import record_uses

    with db:
        record_uses(db)
    progress("provenance")
    index_locations(db)
    progress("snapshot")
    latest = max((m.received_at for m in messages), default=None)
    with db:
        check(db)
        cursor = db.execute(
            "INSERT INTO snapshots(imported_at,latest_message_at,run_id) VALUES (?,?,?)",
            (
                (clock() if clock else None).isoformat() if clock else timestamp(),
                latest.isoformat() if latest else None,
                run_id,
            ),
        )
        review_count = db.execute(
            "SELECT COUNT(*) FROM triage WHERE COALESCE(corrected_category,category)='needs_review'"
        ).fetchone()[0]
        emit(
            db,
            Kind.PUBLISHED,
            Snapshot(counts["triaged"], review_count),
            run_id=run_id,
            entity_type="snapshot",
            entity_id=cursor.lastrowid,
            snapshot_version=cursor.lastrowid,
            source=provenance,
            dedupe_key=f"run:{run_id}:published",
        )
    return counts


def staged_import(db, settings, run_id, root, source, provenance, clock):
    """Publish data together; Pause and the ledger stay writable in the live database."""
    version = db.execute("SELECT generation FROM domain_generation WHERE id=1").fetchone()[0]
    with TemporaryDirectory(prefix="import-stage-", dir=settings.data_root) as directory:
        path = Path(directory) / "stage.sqlite"
        with closing(connect(path)) as staged:
            db.backup(staged)
            journal_cursor = staged.execute(
                "SELECT COALESCE(MAX(id),0) FROM agent_steps"
            ).fetchone()[0]
            counts = import_pipeline(
                staged,
                run_id,
                root,
                source,
                provenance,
                clock=clock,
                contacts=settings.personal_contacts,
                progress=lambda name: stage(db, run_id, name),
            )
        db.execute("ATTACH DATABASE ? AS import_stage", (str(path),))
        try:
            db.execute("BEGIN IMMEDIATE")
            with db:
                check(db)
                if (
                    db.execute("SELECT generation FROM domain_generation WHERE id=1").fetchone()[0]
                    != version
                ):
                    raise RuntimeError("Local state changed during import; retry explicitly")
                # Trusted schema identifiers only. No source content becomes SQL.
                for table in (
                    "messages",
                    "message_history",
                    "attachments",
                    "triage",
                    "message_extractions",
                    "opportunities",
                    "opportunity_revisions",
                    "fields",
                    "roles",
                    "merge_suggestions",
                    "packs",
                    "attachment_locations",
                    "attachment_recoveries",
                    "snapshots",
                    "learned_rule_uses",
                ):
                    db.execute(
                        f"INSERT OR REPLACE INTO main.{table} SELECT * FROM import_stage.{table}"
                    )
                db.execute("DELETE FROM roles WHERE id NOT IN (SELECT id FROM import_stage.roles)")
                # Allocate fresh live IDs. Concurrent telemetry may have consumed staged IDs.
                db.execute(
                    "INSERT INTO main.agent_steps(schema_version,occurred_at,recorded_at,actor,"
                    "kind,run_id,correlation_id,entity_type,entity_id,revision_id,snapshot_version,"
                    "phase,outcome,facts_json,source_refs_json,dedupe_key,source) "
                    "SELECT schema_version,occurred_at,?,actor,kind,run_id,correlation_id,"
                    "entity_type,entity_id,revision_id,snapshot_version,phase,outcome,facts_json,"
                    "source_refs_json,dedupe_key,source FROM import_stage.agent_steps WHERE id>? "
                    "AND phase='committed_result' ORDER BY id",
                    (timestamp(), journal_cursor),
                )
        finally:
            db.execute("DETACH DATABASE import_stage")
    return counts


def execute(
    settings,
    run_id,
    kind,
    *,
    root=None,
    source="export",
    provenance="synthetic",
    opportunity_id=None,
    demo=False,
    clock=None,
):
    with closing(connect(settings.db_path)) as db:
        counts, status, error, pack_id = {}, "success", None, None
        try:
            with scope(run_id=run_id, source=provenance):
                if kind == "import":
                    counts = staged_import(db, settings, run_id, root, source, provenance, clock)
                else:
                    from inbound.packs.build import create_pack

                    stage(db, run_id, "pack")
                    pack = create_pack(
                        db, opportunity_id, demo=demo, settings=settings, run_counts=counts
                    )
                    pack_id = pack["id"]
                    counts = {"built": 1}
        except Exception as exc:  # noqa: BLE001 - background failures must finish their safe ledger row
            db.rollback()
            status = "paused" if isinstance(exc, PausedError) else "failed"
            error = type(exc).__name__
        finally:
            if status != "success":
                emit(
                    db,
                    Kind.IMPORT_FAILED if kind == "import" else Kind.PACK_FAILED,
                    Empty(),
                    run_id=run_id,
                    source=provenance,
                    entity_type="run",
                    entity_id=run_id,
                    dedupe_key=f"run:{run_id}:failed",
                )
            db.execute(
                "UPDATE runs SET finished_at=?,status=?,counts_json=?,error=?,pack_id=? WHERE id=?",
                (timestamp(), status, json.dumps(counts), error, pack_id, run_id),
            )
            db.commit()


def interrupt_runs(db):
    """Called once by the server on restart, never by a read or reconnect."""
    with db:
        for row in db.execute("SELECT * FROM runs WHERE status='running'").fetchall():
            db.execute(
                "UPDATE runs SET status='failed',error='Interrupted',finished_at=? WHERE id=?",
                (timestamp(), row["id"]),
            )
            emit(
                db,
                Kind.INTERRUPTED,
                Empty(),
                run_id=row["id"],
                entity_type="run",
                entity_id=row["id"],
                dedupe_key=f"run:{row['id']}:interrupted",
            )
