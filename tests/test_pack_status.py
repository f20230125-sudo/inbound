from dataclasses import replace
from datetime import timedelta

import pytest

from inbound.db import import_messages
from inbound.extract.pipeline import extract_messages
from inbound.packs.build import create_pack, set_status
from inbound.triage.rules import triage_messages
from tests.m2_helpers import CLOCK, message
from tests.m3_helpers import opportunity


def test_provisional_requires_acknowledgement(database):
    result = create_pack(database, opportunity(database, "P-D16"), demo=True)
    assert result["checks"]["provisional"]
    assert "Provisional preview" in result["rendered"]["label"]
    with pytest.raises(ValueError, match="acknowledge"):
        set_status(database, result["id"], "reviewed")
    set_status(database, result["id"], "reviewed", acknowledge_blocker=True)
    assert database.execute("SELECT status FROM packs").fetchone()[0] == "reviewed"


def test_new_revision_invalidates_reviewed_pack(database):
    result = create_pack(database, opportunity(database, "P-D01"), demo=True)
    set_status(database, result["id"], "reviewed")
    original = message("P-D01")
    newer = replace(
        original,
        provider_id="m3-revision",
        sent_at=original.sent_at + timedelta(hours=2),
        body_text="CV Submission Deadline: 29 October 2026, 08:00AM",
    )
    import_messages(database, [newer])
    triage_messages(database)
    extract_messages(database, clock=lambda: CLOCK)
    assert database.execute("SELECT status FROM packs").fetchone()[0] == "needs_review"
    with pytest.raises(ValueError, match="revision"):
        set_status(database, result["id"], "reviewed")
