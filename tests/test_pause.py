from pathlib import Path

import pytest

from inbound.__main__ import main
from inbound.db import connect, import_messages
from inbound.pause import PausedError, check, set_paused
from inbound.sources.export_txt import load


def test_persistence(tmp_path):
    path = tmp_path / "pause.sqlite"
    with connect(path) as db:
        set_paused(db, True)
    with connect(path) as db:
        with pytest.raises(PausedError):
            check(db)
        set_paused(db, False)
        check(db)


def test_between_stages(database):
    message = next(load(Path("fixtures/export_sample"), "synthetic"))

    def interrupted():
        yield message
        set_paused(database, True)
        yield message

    with pytest.raises(PausedError):
        import_messages(database, interrupted())
    assert database.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    with pytest.raises(PausedError):
        check(database)


def test_cli_blocks_and_resume_exempt(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOUND_DATA_ROOT", str(tmp_path))
    assert main(["pause"]) == 0
    assert (
        main(
            [
                "import",
                "--source",
                "export",
                "--path",
                "fixtures/export_sample",
                "--provenance",
                "synthetic",
            ]
        )
        == 2
    )
    assert main(["resume"]) == 0
    assert (
        main(
            [
                "import",
                "--source",
                "export",
                "--path",
                "fixtures/export_sample",
                "--provenance",
                "synthetic",
            ]
        )
        == 0
    )


def test_pause_blocks_other_work(database, tmp_path):
    from eval.triage_baseline import baseline
    from inbound.triage.rules import triage_messages

    set_paused(database, True)
    with pytest.raises(PausedError):
        triage_messages(database)
    with pytest.raises(PausedError):
        baseline(database, tmp_path)
