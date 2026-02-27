from inbound.digest import plain_text, today


def test_empty(database):
    result = today(database)
    assert result["snapshot"]["stale"]
    assert result["deadlines_48h"] == []
    assert "Snapshot may be out of date" in plain_text(result)


def test_summary(database):
    from pathlib import Path

    from inbound.db import import_messages
    from inbound.extract.pipeline import extract_messages
    from inbound.sources.export_txt import load
    from inbound.triage.rules import triage_messages
    from tests.m2_helpers import CLOCK

    import_messages(database, load(Path("fixtures/export_sample"), "synthetic"))
    triage_messages(database)
    extract_messages(database, clock=lambda: CLOCK)
    result = today(database, CLOCK)
    assert result["deadlines_48h"] and result["new_calls"] and result["admin_tasks"]
    assert all(len(x["deadline"]["normalized"]) > 10 for x in result["deadlines_48h"])
    assert any(x["provider_id"] == "P-D21" for x in result["date_only"])
    assert any(x["provider_id"] == "P-D06" for x in result["attention"])


def test_snapshot_age_and_dubai_day(database):
    from datetime import datetime, timedelta

    from inbound.digest import snapshot_metadata

    now = datetime.fromisoformat("2026-10-28T02:30:00+04:00")
    with database:
        database.execute(
            "INSERT INTO snapshots(imported_at) VALUES (?)",
            ((now - timedelta(hours=3)).isoformat(),),
        )
    # Only three hours old, but from the previous Dubai day.
    assert snapshot_metadata(database, now)["stale"]
    with database:
        database.execute("UPDATE snapshots SET imported_at=?", (now.isoformat(),))
    assert not snapshot_metadata(database, now)["stale"]
    assert snapshot_metadata(database, now + timedelta(hours=13))["stale"]


def test_submitted_skipped_not_outstanding_and_unknowns_visible(database):
    from tests.m2_helpers import CLOCK
    from tests.m3_helpers import opportunity

    oid = opportunity(database, "P-D12")
    opportunity(database, "P-D10")
    before = today(database, CLOCK)
    assert any(e["id"] == oid for e in before["deadlines_48h"])
    assert before["uncertain_deadlines"]
    for status in ("skipped", "submitted_by_me"):
        with database:
            database.execute("UPDATE opportunities SET status=? WHERE id=?", (status, oid))
        after = today(database, CLOCK)
        assert not any(
            e["id"] == oid
            for key in ("deadlines_48h", "new_calls", "attention")
            for e in after[key]
            if e["kind"] == "call"
        )
