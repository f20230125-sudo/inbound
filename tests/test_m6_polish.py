"""Fictional regressions from the sanitized real-mail findings; no rule changes."""

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from inbound.__main__ import main
from inbound.api import create_app
from inbound.db import connect, import_messages
from inbound.digest import plain_text, today
from inbound.extract.pipeline import extract_messages
from inbound.models import Message
from inbound.settings import Settings
from inbound.triage.rules import triage_messages

NOW = datetime(2026, 10, 28, 5, tzinfo=UTC)


def fictional_call():
    return Message(
        provider_id="m6-fictional", thread_id="m6-fictional", sent_at=NOW, received_at=NOW,
        sender="ps@dubai.bits-pilani.ac.in", source="synthetic",
        subject="Call for CV - PS II - Second Semester 2026-2027 - Lantern Forge,DSO",
        body_text=(
            "Lantern Forge has expressed their interest to hire students.\nCity: Dubai\n"
            "Job Title & JD\n1. Research Intern\nExpected Skills:\n- Python\n"
            "2. Backend Intern\nExpected Skills:\n- SQL\n"
            "3. Design Intern\nExpected Skills:\n- Layout\n"
            "4. Test Intern\nExpected Skills:\n- Testing\n"
        ),
    )


def prepare(db, message=None):
    import_messages(db, [message or fictional_call()])
    triage_messages(db)
    extract_messages(db, clock=lambda: NOW)
    return db.execute("SELECT id FROM opportunities").fetchone()[0]


@pytest.mark.parametrize("source", ["export", "eml"])
def test_cli_import_publishes_snapshot_like_api(tmp_path, monkeypatch, capsys, source):
    root = tmp_path / "source"
    root.mkdir()
    if source == "export":
        (root / "fictional.txt").write_text(
            "id: m6-mail\nthread_id: m6-mail\ndate: 2026-10-28T05:00:00+00:00\n"
            "from: friend@fictional.invalid\nsubject: Fictional hello\nbody_complete: true\n"
            "to:\ncc:\nbcc:\nlabels:\nattachments:\nbody_exported: fictional\n"
            "---\nHello from a fictional friend.\n", encoding="utf8",
        )
    else:
        (root / "fictional.eml").write_text(
            "Message-ID: <m6@fictional.invalid>\nDate: Wed, 28 Oct 2026 05:00:00 +0000\n"
            "From: friend@fictional.invalid\nSubject: Fictional hello\n\nHello.\n",
            encoding="utf8",
        )
    settings = Settings(data_root=tmp_path / "cli")
    monkeypatch.setenv("INBOUND_DATA_ROOT", str(settings.data_root))
    args = ["import", "--source", source, "--path", str(root), "--provenance", "synthetic"]
    for version in (1, 2):
        assert main(args) == 0
        with connect(settings.db_path) as db:
            snapshot = today(db)["snapshot"]
            assert snapshot["version"] == version
            assert not snapshot["stale"]
            assert datetime.fromisoformat(snapshot["latest_message_at"]) == NOW
            run = db.execute("SELECT * FROM runs WHERE id=?", (snapshot["run_id"],)).fetchone()
            assert run["status"] == "success"
            assert run["source_type"] == source
        assert main(["digest"]) == 0
        output = capsys.readouterr().out
        assert "Last successful import: Not recorded" not in output
        assert "Snapshot may be out of date" not in output
    app = create_app({"TESTING": True, "ASYNC_WORK": False,
                      "SETTINGS": Settings(data_root=tmp_path / "api"), "IMPORT_ROOT": root,
                      "SOURCE_FORMAT": source, "SOURCE_PROVENANCE": "synthetic"})
    with app.test_client() as client:
        token = client.get("/api/settings").json["csrf_token"]
        assert client.post("/api/import", json={}, headers={"X-CSRF-Token": token}).status_code == 202
        api_snapshot = client.get("/api/today").json["snapshot"]
        assert api_snapshot["latest_message_at"] == snapshot["latest_message_at"]
        assert not api_snapshot["stale"]


def test_cli_failed_import_keeps_last_successful_snapshot(tmp_path, monkeypatch, capsys):
    settings = Settings(data_root=tmp_path)
    monkeypatch.setenv("INBOUND_DATA_ROOT", str(tmp_path))
    with connect(settings.db_path) as db:
        db.execute("INSERT INTO snapshots(imported_at) VALUES (?)", (datetime.now(UTC).isoformat(),))
    assert main(["import", "--source", "export", "--path", str(tmp_path / "missing"),
                 "--provenance", "synthetic"]) == 2
    with connect(settings.db_path) as db:
        result = today(db)
        assert result["snapshot"]["version"] == 1
        assert result["snapshot"]["latest_import_failure"]
    capsys.readouterr()


@pytest.mark.parametrize("pack", [False, True])
def test_titles_keep_observations_and_use_pack_recommendation(tmp_path, pack):
    settings = Settings(data_root=tmp_path)
    with connect(settings.db_path) as db:
        oid = prepare(db)
        revision = db.execute("SELECT id FROM opportunity_revisions").fetchone()[0]
        if pack:
            role = db.execute("SELECT id,title FROM roles WHERE title='Backend Intern'").fetchone()
            db.execute(
                "INSERT INTO packs(id,opportunity_id,revision_id,role_id,status,selection_json,"
                "files_json,checks_json,created_at) VALUES ('fictional-pack',?,?,?,'needs_review',"
                "?,'{}','{}',?)",
                (oid, revision, role["id"], json.dumps({"recommended_role": dict(role)}), NOW.isoformat()),
            )
            db.commit()
        expected = f"Lantern Forge · {'Backend Intern' if pack else '4 roles'} · DSO (Dubai)"
        summary = today(db, NOW)
        assert summary["new_calls"][0]["display_title"] == expected
        assert expected in plain_text(summary)
        assert summary["new_calls"][0]["city"] == ["DSO", "Dubai"]
    app = create_app({"TESTING": True, "SETTINGS": settings, "CLOCK": lambda: NOW})
    with app.test_client() as client:
        assert client.get("/api/today").json["new_calls"][0]["display_title"] == expected
        for value in (client.get("/api/opportunities").json[0],
                      client.get(f"/api/opportunities/{oid}").json):
            assert value["display_title"] == expected
            assert value["city_display"] == "DSO (Dubai)"
            assert value["fields"]["city"]["normalized"] == ["DSO", "Dubai"]
            assert len(value["fields"]["city"]["observations"]) == 2


def test_unknown_company_fallback_strips_call_prefix_and_reply_chain(database):
    message = replace(fictional_call(),
                      subject="Re: Fwd: Re: Call for CV - PS II - Second Semester 2026-2027 - ZK?",
                      body_text="Please consult the exported attachment.")
    prepare(database, message)
    assert today(database, NOW)["new_calls"][0]["display_title"] == "ZK?"
