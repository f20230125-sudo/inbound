"""Create an idempotent, synthetic desk with a fictional approved pack."""

import json
from contextlib import closing
from datetime import datetime

from inbound.db import connect
from inbound.evidence.registry import import_evidence
from inbound.ledger import timestamp
from inbound.packs.build import create_pack
from inbound.pause import check
from inbound.settings import REPO, Settings
from inbound.work import import_pipeline, start_run


def build_demo(settings=None):
    settings = settings or Settings()
    definitions = json.loads((REPO / "fixtures/manifest.json").read_text("utf8"))
    clock = datetime.fromisoformat(definitions["clock"])
    with closing(connect(settings.db_path)) as db:
        check(db)
        if db.execute("SELECT 1 FROM messages WHERE source<>'synthetic'").fetchone():
            raise ValueError("Demo requires a synthetic-only database")
        run_id = start_run(db, "import", source_type="export", source_provenance="synthetic")
        try:
            counts = import_pipeline(
                db,
                run_id,
                REPO / "fixtures/export_sample",
                "export",
                "synthetic",
                clock=lambda: clock,
            )
            import_evidence(db, demo=True)
        except Exception as exc:
            db.execute(
                "UPDATE runs SET status=?,error=?,finished_at=? WHERE id=?",
                ("failed", type(exc).__name__, timestamp(), run_id),
            )
            db.commit()
            raise
        with db:
            db.execute(
                "INSERT INTO settings VALUES ('demo_clock',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (clock.isoformat(),),
            )
            db.execute(
                "UPDATE runs SET status='success',finished_at=?,counts_json=? WHERE id=?",
                (timestamp(), json.dumps(counts), run_id),
            )
        oid = db.execute(
            "SELECT r.opportunity_id FROM opportunity_revisions r "
            "JOIN messages m ON m.id=r.message_id WHERE m.provider_id=?",
            ("P-D12",),
        ).fetchone()[0]
        existing = db.execute(
            "SELECT id FROM packs WHERE opportunity_id=? AND demo=1 "
            "AND status IN ('needs_review','reviewed','submitted_by_me')",
            (oid,),
        ).fetchone()
        pack_id = (
            existing[0] if existing else create_pack(db, oid, demo=True, settings=settings)["id"]
        )
        return {
            "messages": db.execute("SELECT count(*) FROM messages").fetchone()[0],
            "opportunity_id": oid,
            "pack_id": pack_id,
            "clock": clock.isoformat(),
        }
