import json
from pathlib import Path

from inbound.db import import_messages
from inbound.extract.pipeline import extract_messages
from inbound.sources.export_txt import load
from inbound.triage.rules import triage_messages
from tests.m2_helpers import CLOCK


def snapshot():
    return json.loads(Path("fixtures/demo_evidence.json").read_text(encoding="utf8"))


def opportunity(db, identity="P-D12"):
    messages = [
        m for m in load(Path("fixtures/export_sample"), "synthetic") if m.provider_id == identity
    ]
    import_messages(db, messages)
    triage_messages(db)
    extract_messages(db, clock=lambda: CLOCK)
    return db.execute(
        "SELECT opportunity_id FROM opportunity_revisions r "
        "JOIN messages m ON m.id=r.message_id WHERE m.provider_id=?",
        (identity,),
    ).fetchone()[0]
