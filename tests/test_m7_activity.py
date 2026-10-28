"""Outside applications are human declarations, independent of pack review."""

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from inbound.__main__ import main
from inbound.api import create_app
from inbound.db import connect, import_messages
from inbound.extract.pipeline import extract_messages
from inbound.pause import set_paused
from inbound.settings import Settings
from inbound.triage.rules import triage_messages
from inbound.work import execute, start_run
from tests.test_m6_polish import NOW, fictional_call, prepare


@pytest.fixture
def desk(tmp_path):
    settings = Settings(data_root=tmp_path)
    with connect(settings.db_path) as db:
        message = replace(fictional_call(), body_text=fictional_call().body_text +
                          "\nCV Submission Deadline: 28 October 2026, 08:00AM\n")
        oid = prepare(db, message)
    app = create_app({"TESTING": True, "SETTINGS": settings, "ASYNC_WORK": False})
    with app.test_client() as client:
        token = client.get("/api/settings").json["csrf_token"]
        yield app, client, oid, {"X-CSRF-Token": token}


def payload(client, oid, **changes):
    op = client.get(f"/api/opportunities/{oid}").json
    return {
        "applied_at": "2026-10-28T08:15:00+04:00",
        "human_submission": True,
        "note": "Applied myself using my own CV.",
        "follow_up": "2026-11-02",
        "expected_revision_id": op["revision_id"],
        "expected_activity_id": (op.get("outside_application") or {}).get("id"),
        **changes,
    }


@pytest.mark.parametrize("kind", ["no_pack", "blocked", "expired", "unreviewed_pack"])
def test_record_any_opportunity_without_reviewing_a_pack(desk, kind):
    app, client, oid, headers = desk
    with connect(app.config["SETTINGS"].db_path) as db:
        if kind == "blocked":
            db.execute("UPDATE opportunities SET status='blocked',blocked_reason='Missing JD'")
        if kind == "expired":
            app.config["CLOCK"] = lambda: NOW + timedelta(days=100)
        if kind == "unreviewed_pack":
            revision = client.get(f"/api/opportunities/{oid}").json["revision_id"]
            db.execute(
                "INSERT INTO packs(id,opportunity_id,revision_id,status,selection_json,"
                "files_json,checks_json,created_at) VALUES ('m7-pack',?,?,'needs_review',"
                "'{}','{}','{}',?)", (oid, revision, NOW.isoformat()),
            )
    body = payload(client, oid)
    result = client.post(f"/api/opportunities/{oid}/applied", json=body, headers=headers)
    assert result.status_code == 200
    op = client.get(f"/api/opportunities/{oid}").json
    if kind == "expired":
        assert op["expired"] is True
    activity = op["outside_application"]
    assert activity["applied_at"] == "2026-10-28T04:15:00+00:00"
    assert activity["follow_up"] == "2026-11-02"
    assert activity["recorded_at"] and activity["note"] == body["note"]
    assert op["review_history"][-1]["action"] == "applied_outside"
    assert not any(e["action"] == "reviewed" for e in op["review_history"])
    assert all(p["status"] == "needs_review" for p in op["packs"])
    if kind == "blocked":
        assert op["status"] == "blocked" and op["blocked_reason"] == "Missing JD"
    summary = client.get("/api/today").json
    assert summary["outside_applications"][0]["outside_application"] == activity
    assert client.get("/api/opportunities").json[0]["outside_application"] == activity


def test_idempotent_retry_correction_history_and_stale_writes(desk):
    app, client, oid, headers = desk
    url = f"/api/opportunities/{oid}/applied"
    body = payload(client, oid)
    first = client.post(url, json=body, headers=headers).json
    assert client.post(url, json=body, headers=headers).json == first
    correction = payload(client, oid, applied_at="2026-10-27T22:00:00Z", note="Corrected time")
    second = client.post(url, json=correction, headers=headers)
    assert second.status_code == 200 and second.json["id"] != first["id"]
    stale = {**body, "note": "Overwrite from old tab"}
    assert client.post(url, json=stale, headers=headers).status_code == 409
    op = client.get(f"/api/opportunities/{oid}").json
    assert [e["details"]["note"] for e in op["review_history"]] == [body["note"], "Corrected time"]
    assert op["outside_application"]["applied_at"] == "2026-10-27T22:00:00+00:00"
    with connect(app.config["SETTINGS"].db_path) as db:
        newer = replace(fictional_call(), provider_id="m7-revision", sent_at=NOW + timedelta(hours=1))
        import_messages(db, [newer])
        triage_messages(db)
        extract_messages(db)
    assert client.post(url, json=correction, headers=headers).status_code == 409


def test_reimport_preserves_activity_in_staged_publication(desk):
    app, client, oid, headers = desk
    client.post(f"/api/opportunities/{oid}/applied", json=payload(client, oid), headers=headers)
    before = client.get(f"/api/opportunities/{oid}").json
    settings = app.config["SETTINGS"]
    with connect(settings.db_path) as db:
        run_id = start_run(db, "import", source_type="export")
    execute(settings, run_id, "import", root=Path("fixtures/export_sample"), provenance="synthetic")
    with connect(settings.db_path) as db:
        assert db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()[0] == "success"
    after = client.get(f"/api/opportunities/{oid}").json
    assert after["outside_application"] == before["outside_application"]
    assert after["review_history"] == before["review_history"]


@pytest.mark.parametrize("change", [
    {"human_submission": False}, {"human_submission": 1}, {"applied_at": "2026-10-28"},
    {"applied_at": "2026-10-28T08:00:00"}, {"follow_up": "2026-02-30"},
    {"note": "x" * 1001}, {"note": 42}, {"expected_revision_id": None},
    {"unexpected": True},
])
def test_invalid_declarations_do_not_record(desk, change):
    _, client, oid, headers = desk
    assert client.post(f"/api/opportunities/{oid}/applied", json=payload(client, oid, **change),
                       headers=headers).status_code in {400, 409}
    assert not client.get(f"/api/opportunities/{oid}").json.get("outside_application")


def test_route_guards_and_import_conflict(desk):
    app, client, oid, headers = desk
    url = f"/api/opportunities/{oid}/applied"
    body = payload(client, oid)
    assert client.post(url, json=body).status_code == 403
    assert client.post(url, json=body, headers=headers, base_url="http://evil.invalid").status_code == 403
    app.config["APP_MODE"] = "replay"
    assert client.post(url, json=body, headers=headers).status_code == 405
    app.config["APP_MODE"] = "local"
    with connect(app.config["SETTINGS"].db_path) as db:
        set_paused(db, True)
    assert client.post(url, json=body, headers=headers).status_code == 409
    with connect(app.config["SETTINGS"].db_path) as db:
        set_paused(db, False)
        start_run(db, "import")
    assert client.post(url, json=body, headers=headers).status_code == 409


def test_cli_requires_declaration_is_idempotent_and_honors_pause_replay(desk, monkeypatch, capsys):
    app, client, oid, _ = desk
    monkeypatch.setenv("INBOUND_DATA_ROOT", str(app.config["SETTINGS"].data_root))
    args = ["applied", str(oid), "--at", "2026-10-28T08:15:00+04:00",
            "--note", "CLI declaration", "--follow-up", "2026-11-02"]
    assert main(args) == 2
    assert main([*args, "--i-applied-myself"]) == 0
    first = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert main([*args, "--i-applied-myself"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == first["id"]
    with connect(app.config["SETTINGS"].db_path) as db:
        set_paused(db, True)
    assert main([*args, "--i-applied-myself"]) == 2
    with connect(app.config["SETTINGS"].db_path) as db:
        set_paused(db, False)
    monkeypatch.setenv("APP_MODE", "replay")
    assert main([*args, "--i-applied-myself"]) == 2
    assert len(client.get(f"/api/opportunities/{oid}").json["review_history"]) == 1


@pytest.mark.parametrize("demo,enabled,mode,expected", [
    (True, True, "local", 200), (False, True, "local", 404),
    (True, False, "local", 404), (True, True, "replay", 405),
])
def test_clock_override_is_test_only_and_demo_only(desk, demo, enabled, mode, expected):
    app, client, _, headers = desk
    app.config.update(DEMO=demo, TEST_CLOCK=enabled, APP_MODE=mode)
    response = client.post("/api/test/clock", json={"now": "2026-10-28T08:01:00+04:00"},
                           headers=headers)
    assert response.status_code == expected
    if expected == 200:
        assert client.get("/api/today").json["now"] == "2026-10-28T08:01:00+04:00"
        assert client.get("/api/settings").json["frozen_clock"]
