from pathlib import Path

from inbound.db import connect
from inbound.settings import Settings
from inbound.work import execute, start_run


def test_failed_import_publishes_no_partial_rows(tmp_path, monkeypatch):
    from inbound import work

    settings = Settings(data_root=tmp_path)
    with connect(settings.db_path) as db:
        run_id = start_run(db, "import", source_type="export")

    def broken_extract(db, **kwargs):
        raise ValueError("synthetic failure after staging messages and triage")

    monkeypatch.setattr(work, "extract_messages", broken_extract)
    execute(settings, run_id, "import", root=Path("fixtures/export_sample"), provenance="synthetic")
    with connect(settings.db_path) as db:
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM snapshots").fetchone()[0] == 0
        assert db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()[0] == "failed"


def test_pause_in_live_database_blocks_staged_next_stage(tmp_path, monkeypatch):
    from inbound import work
    from inbound.pause import set_paused

    settings = Settings(data_root=tmp_path)
    with connect(settings.db_path) as db:
        run_id = start_run(db, "import", source_type="export")
    triage = work.triage_messages

    def pause(db, **kwargs):
        result = triage(db, **kwargs)
        with connect(settings.db_path) as live:
            set_paused(live, True)
        return result

    monkeypatch.setattr(work, "triage_messages", pause)
    execute(settings, run_id, "import", root=Path("fixtures/export_sample"), provenance="synthetic")
    with connect(settings.db_path) as db:
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        row = db.execute("SELECT status,stage FROM runs WHERE id=?", (run_id,)).fetchone()
        assert row["status"] == "paused" and row["stage"] == "triage"
