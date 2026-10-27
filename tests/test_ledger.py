import json

import pytest

from inbound.ledger import run


def test_safe_counts_and_errors(database):
    with run(database, "import") as counts:
        counts.update(imported=3, unchanged=2, changed=1)
    with pytest.raises(ValueError), run(database, "import"):
        raise ValueError("body SYNTHETIC-CANARY api_key=synthetic-secret")
    rows = database.execute("SELECT * FROM runs ORDER BY id").fetchall()
    assert json.loads(rows[0]["counts_json"])["imported"] == 3
    assert rows[0]["status"] == "success"
    assert rows[1]["status"] == "failed"
    assert rows[1]["error"] == "ValueError"
    serialized = str([dict(row) for row in rows])
    assert "SYNTHETIC-CANARY" not in serialized and "synthetic-secret" not in serialized


def test_ledger_drops_unapproved_values(database):
    with run(database, "triage") as counts:
        counts["body"] = "SYNTHETIC-CANARY"
        counts["imported"] = "api_key=synthetic-secret"
    assert database.execute("SELECT counts_json FROM runs").fetchone()[0] == "{}"


def test_cli_import_failure_recorded(tmp_path, monkeypatch):
    from inbound.__main__ import main
    from inbound.db import connect

    monkeypatch.setenv("INBOUND_DATA_ROOT", str(tmp_path))
    assert (
        main(
            [
                "import",
                "--source",
                "export",
                "--path",
                str(tmp_path / "absent"),
                "--provenance",
                "synthetic",
            ]
        )
        == 2
    )
    db = connect(tmp_path / "demo.sqlite")
    row = db.execute("SELECT status,error,model_calls,cache_hits FROM runs").fetchone()
    assert tuple(row) == ("failed", "SourceError", 0, 0)
    db.close()


def test_cli_never_prints_source_error_text(tmp_path, monkeypatch, capsys):
    from inbound.__main__ import main

    monkeypatch.setenv("INBOUND_DATA_ROOT", str(tmp_path))
    source = tmp_path / "exports"
    source.mkdir()
    (source / "bad.txt").write_text("SYNTHETIC-CANARY-R4-J05-7E4B api_key=synthetic-secret")
    assert (
        main(["import", "--source", "export", "--path", str(source), "--provenance", "private"])
        == 2
    )
    output = capsys.readouterr().out
    assert "SYNTHETIC-CANARY" not in output
    assert "synthetic-secret" not in output
