import json
from pathlib import Path

import pytest

from inbound.api import create_app
from inbound.db import connect
from inbound.settings import Settings


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "ASYNC_WORK": False,
            "SETTINGS": Settings(data_root=tmp_path),
            "IMPORT_ROOT": Path("fixtures/export_sample").resolve(),
            "SOURCE_PROVENANCE": "synthetic",
            "DEMO": True,
        }
    )


def post(client, url, body=None, **kwargs):
    token = client.get("/api/settings").json["csrf_token"]
    return client.post(url, json=body or {}, headers={"X-CSRF-Token": token}, **kwargs)


def test_smoke_and_import(app):
    with app.test_client() as c:
        for url in [
            "/api/settings",
            "/api/today",
            "/api/messages",
            "/api/opportunities",
            "/api/runs",
        ]:
            assert c.get(url).status_code == 200
        result = post(c, "/api/import").json
        assert result["run_id"]
        assert len(c.get("/api/messages").json) == 190
        assert c.get("/api/today").json["snapshot"]["version"] == 1
        ops = c.get("/api/opportunities").json
        detail = c.get(f"/api/opportunities/{ops[0]['id']}").json
        assert detail["revisions"] and detail["fields"] and detail["roles"]
        assert c.get("/api/runs").json[0]["status"] == "completed"


def test_full_provenance_locations(app):
    with app.test_client() as c:
        post(c, "/api/import")
        with connect(app.config["SETTINGS"].db_path) as db:
            identities = {
                row["provider_id"]: row["opportunity_id"]
                for row in db.execute(
                    "SELECT m.provider_id,r.opportunity_id FROM messages m "
                    "JOIN opportunity_revisions r ON r.message_id=m.id"
                )
            }
        for case, expected in [("P-D15", "pdf_page"), ("P-D19", "docx_paragraph")]:
            detail = c.get(f"/api/opportunities/{identities[case]}").json
            assert any(
                location["kind"] == expected
                for attachment in detail["attachments"]
                for location in attachment["locations"]
            )
            requirements = detail["roles"][0]["requirements"]
            assert requirements and requirements[0]["source_text"]
            assert requirements[0]["provenance"]["locations"]
        reminder = c.get(f"/api/opportunities/{identities['P-D08']}").json
        deadline = reminder["fields"]["deadline"]
        assert deadline["anchor"] and deadline["provenance"]["sent_at"]
        assert deadline["provenance"]["revision_id"] == reminder["revision_id"]
        assert reminder["fields"]["company"]["provenance"]["message_id"] == "P-D08"
        # The frozen reminder repeats company/stipend. A later sparse revision inherits them.
        from dataclasses import replace
        from datetime import timedelta

        from inbound.db import import_messages
        from inbound.extract.pipeline import extract_messages
        from inbound.triage.rules import triage_messages
        from tests.m2_helpers import message

        original = message("P-D08")
        sparse = replace(
            original,
            provider_id="sparse-revision",
            sent_at=original.sent_at + timedelta(hours=1),
            body_text="Revised deadline: 30 October 2026, 08:00AM",
        )
        with connect(app.config["SETTINGS"].db_path) as db:
            import_messages(db, [sparse])
            triage_messages(db)
            extract_messages(db)
        updated = c.get(f"/api/opportunities/{identities['P-D08']}").json
        assert updated["fields"]["stipend"]["inherited"]
        assert updated["fields"]["stipend"]["provenance"]["message_id"] == "P-D08"


def test_pack_root_symlink_escape_is_rejected(app, monkeypatch):
    # Simulate resolved packs directory escaping its configured data root, without requiring
    # Windows symlink privileges or writing anywhere outside the test directory.
    from unittest.mock import patch

    from werkzeug.exceptions import NotFound

    from inbound.api.data import artifact

    configured = app.config["SETTINGS"].data_root
    outside = configured.parent / "outside"
    (outside / "pack").mkdir(parents=True, exist_ok=True)
    (outside / "pack/x.pdf").write_bytes(b"%PDF-synthetic")
    original = Path.resolve

    def resolved(path, *args, **kwargs):
        if path == configured / "packs" or path.is_relative_to(configured / "packs"):
            return outside / path.relative_to(configured / "packs")
        return original(path, *args, **kwargs)

    row = {"id": "pack", "files_json": json.dumps({"pdf": str(configured / "packs/pack/x.pdf")})}
    with patch.object(Path, "resolve", resolved), pytest.raises(NotFound):
        artifact(row, app.config["SETTINGS"])


@pytest.mark.parametrize(
    "url",
    [
        "/api/import",
        "/api/settings",
        "/api/messages/1/category",
        "/api/opportunities/1/pack",
        "/api/opportunities/1/status",
        "/api/packs/missing/status",
    ],
)
def test_guards(app, url):
    with app.test_client() as c:
        assert c.post(url, json={}).status_code == 403
        assert c.post(url, json={}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
        assert post(c, url, base_url="http://evil.invalid:5000").status_code == 403
        app.config["APP_MODE"] = "replay"
        assert c.post(url, json={}).status_code in {403, 405}


def test_pause(app):
    with app.test_client() as c:
        assert post(c, "/api/settings", {"paused": True}).status_code == 200
        for url in ["/api/import", "/api/messages/1/category", "/api/opportunities/1/pack"]:
            assert post(c, url).status_code == 409
        assert post(c, "/api/settings", {"paused": False, "other": True}).status_code == 400
        assert post(c, "/api/settings", {"paused": False}).status_code == 200


def test_replay_sanitized(app):
    app.config["APP_MODE"] = "replay"
    with app.test_client() as c:
        response = c.get("/api/settings")
        assert "csrf_token" not in response.json
        assert "private" not in json.dumps(response.json["paths"]).lower()
        assert str(app.config["SETTINGS"].data_root) not in response.text
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_missing_and_validation(app):
    with app.test_client() as c:
        for url in ["/api/opportunities/999", "/api/packs/no", "/api/packs/no/pdf"]:
            assert c.get(url).status_code == 404
        assert c.get("/api/messages?category=bad").status_code == 400
        assert post(c, "/api/settings", {"paused": "yes"}).status_code == 400
        assert post(c, "/api/opportunities/999/status", {"status": "skipped"}).status_code == 404
        assert post(c, "/api/opportunities/999/pack").status_code == 404
        assert post(c, "/api/packs/no/status", {"status": "reviewed"}).status_code == 404


def test_eml_import_and_skip_transition_limits(app):
    app.config["IMPORT_ROOT"] = Path("fixtures/eml_sample").resolve()
    app.config["SOURCE_FORMAT"] = "eml"
    with app.test_client() as c:
        assert post(c, "/api/import").status_code == 202
        assert len(c.get("/api/messages").json) == 5
        oid = c.get("/api/opportunities").json[0]["id"]
        url = f"/api/opportunities/{oid}/status"
        assert post(c, url, {"status": "new"}).status_code == 400
        assert post(c, url, {"status": "undo_skip"}).status_code == 409
        assert post(c, url, {"status": "skipped", "reason": "x" * 1001}).status_code == 400
        assert post(c, url, {"status": "skipped", "reason": "Not a fit"}).status_code == 200
        assert post(c, url, {"status": "skipped"}).status_code == 409
        assert post(c, url, {"status": "undo_skip"}).status_code == 200


def test_review_and_skip(app):
    with app.test_client() as c:
        post(c, "/api/import")
        with connect(app.config["SETTINGS"].db_path) as db:
            oid = db.execute(
                "SELECT r.opportunity_id FROM opportunity_revisions r "
                "JOIN messages m ON m.id=r.message_id "
                "WHERE m.provider_id='P-D16'"
            ).fetchone()[0]
        assert post(c, f"/api/opportunities/{oid}/status", {"status": "skipped"}).status_code == 200
        assert (
            post(c, f"/api/opportunities/{oid}/status", {"status": "undo_skip"}).status_code == 200
        )
        built = post(c, f"/api/opportunities/{oid}/pack")
        assert built.status_code == 202
        run = c.get("/api/runs").json[0]
        pid = run["pack_id"]
        pack = c.get(f"/api/packs/{pid}").json
        assert c.get(f"/api/packs/{pid}/pdf").status_code == 200
        body = {
            "status": "reviewed",
            "expected_pack_id": pid,
            "expected_revision_id": pack["revision_id"],
        }
        assert post(c, f"/api/packs/{pid}/status", body).status_code == 409
        body["acknowledge_blocker"] = True
        assert post(c, f"/api/packs/{pid}/status", body).status_code == 200
        body["status"] = "submitted_by_me"
        assert post(c, f"/api/packs/{pid}/status", body).status_code == 400
        body["human_submission"] = True
        assert post(c, f"/api/packs/{pid}/status", body).status_code == 200
        body["expected_revision_id"] = -1
        assert post(c, f"/api/packs/{pid}/status", body).status_code == 409
        # Republishing an unchanged snapshot retains the pack and its human events.
        assert post(c, "/api/import").status_code == 202
        assert c.get("/api/runs").json[0]["status"] == "completed"
        assert c.get(f"/api/packs/{pid}").json["status"] == "submitted_by_me"
        assert any(
            e["action"] == "submitted_by_me"
            for e in c.get(f"/api/opportunities/{oid}").json["review_history"]
        )


def test_category_history_and_override_processing(app):
    from inbound.db import import_messages
    from inbound.extract.pipeline import extract_messages
    from inbound.sources.export_txt import load
    from inbound.triage.rules import triage_messages

    with connect(app.config["SETTINGS"].db_path) as db:
        import_messages(
            db,
            [
                m
                for m in load(Path("fixtures/export_sample"), "synthetic")
                if m.provider_id == "P-D12"
            ],
        )
        triage_messages(db)
        mid = db.execute("SELECT id FROM messages").fetchone()[0]
    with app.test_client() as c:
        url = f"/api/messages/{mid}/category"
        assert post(c, url, {"category": "academic"}).status_code == 200
        assert c.get("/api/messages?category=academic").json[0]["original_category"] == "ps_call"
        with connect(app.config["SETTINGS"].db_path) as db:
            extract_messages(db)
            assert db.execute("SELECT count(*) FROM opportunities").fetchone()[0] == 0
        assert post(c, url, {"category": "ps_call"}).status_code == 200
        assert len(c.get("/api/messages").json[0]["classification_history"]) == 2
        assert post(c, "/api/messages/999/category", {"category": "academic"}).status_code == 404
        assert post(c, url, {"category": "bad"}).status_code == 400


def test_snapshot_failure_and_pause_between_stages(app, monkeypatch):
    from inbound import work
    from inbound.pause import set_paused

    with app.test_client() as c:
        post(c, "/api/import")
        original = c.get("/api/today").json["snapshot"]
        real_triage = work.triage_messages

        def pause_after_triage(db, **kwargs):
            count = real_triage(db, **kwargs)
            set_paused(db, True)
            return count

        monkeypatch.setattr(work, "triage_messages", pause_after_triage)
        result = post(c, "/api/import")
        assert result.status_code == 202
        snapshot = c.get("/api/today").json["snapshot"]
        assert snapshot["version"] == original["version"]
        assert snapshot["latest_import_failure"]["status"] == "paused"
        assert c.get("/api/runs").json[0]["status"] == "paused"
        post(c, "/api/settings", {"paused": False})
        monkeypatch.setattr(work, "triage_messages", real_triage)
        app.config["IMPORT_ROOT"] = app.config["SETTINGS"].data_root / "absent"
        post(c, "/api/import")
        assert c.get("/api/today").json["snapshot"]["version"] == original["version"]
        assert c.get("/api/runs").json[0]["status"] == "failed"


def test_duplicate_start_and_real_async_completion(app):
    from threading import Event

    executor = app.extensions["work_executor"]
    original_submit = executor.submit
    pending = []
    executor.submit = lambda *args, **kwargs: pending.append((args, kwargs))
    app.config["ASYNC_WORK"] = True
    try:
        with app.test_client() as c:
            response = post(c, "/api/import")
            assert response.status_code == 202
            assert post(c, "/api/import").status_code == 409
            assert c.get("/api/runs").json[0]["status"] == "running"
        args, kwargs = pending[0]
        done = Event()

        def finish():
            try:
                args[0](*args[1:], **kwargs)
            finally:
                done.set()

        executor.submit = original_submit
        executor.submit(finish)
        assert done.wait(10)
        with app.test_client() as c:
            assert c.get("/api/runs").json[0]["status"] == "completed"
            assert c.get("/api/today").json["snapshot"]["version"] == 1
    finally:
        executor.submit = original_submit


def test_pdf_and_pack_confined_to_configured_root(app, tmp_path):
    from tests.m3_helpers import opportunity

    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-synthetic")
    with connect(app.config["SETTINGS"].db_path) as db:
        oid = opportunity(db)
        revision = db.execute("SELECT id FROM opportunity_revisions").fetchone()[0]
        with db:
            db.execute(
                "INSERT INTO packs(id,opportunity_id,revision_id,status,created_at,"
                "files_json,demo) VALUES ('escape',?,?,'needs_review','2026',?,1)",
                (oid, revision, json.dumps({"pdf": str(outside)})),
            )
    with app.test_client() as c:
        assert c.get("/api/packs/escape/pdf").status_code == 404
        assert c.get("/api/packs/escape").status_code == 404


def test_stale_revision_and_pack_ids_and_conflict(app):
    from inbound.db import import_messages
    from inbound.extract.pipeline import extract_messages
    from inbound.triage.rules import triage_messages
    from tests.m2_helpers import message
    from tests.m3_helpers import opportunity

    with connect(app.config["SETTINGS"].db_path) as db:
        oid = opportunity(db, "P-D02")
    with app.test_client() as c:
        assert post(c, f"/api/opportunities/{oid}/pack").status_code == 202
        run = c.get("/api/runs").json[0]
        pid = run["pack_id"]
        revision = c.get(f"/api/packs/{pid}").json["revision_id"]
        url = f"/api/packs/{pid}/status"
        body = {"status": "reviewed", "expected_pack_id": pid, "expected_revision_id": revision}
        assert post(c, url, {**body, "expected_pack_id": "other"}).status_code == 409
        assert post(c, url, body).status_code == 200
        with connect(app.config["SETTINGS"].db_path) as db:
            import_messages(db, [message("P-D08")])
            triage_messages(db)
            extract_messages(db)
        assert post(c, url, body).status_code == 409
        with connect(app.config["SETTINGS"].db_path) as db:
            assert db.execute("SELECT count(*) FROM review_events WHERE action='reviewed'")
            conflict = opportunity(db, "J09")
        assert post(c, f"/api/opportunities/{conflict}/pack").status_code == 202
        conflict_pid = c.get("/api/runs").json[0]["pack_id"]
        revision = c.get(f"/api/packs/{conflict_pid}").json["revision_id"]
        assert (
            post(
                c,
                f"/api/packs/{conflict_pid}/status",
                {
                    "status": "reviewed",
                    "expected_pack_id": conflict_pid,
                    "expected_revision_id": revision,
                    "acknowledge_blocker": True,
                },
            ).status_code
            == 409
        )


def test_replay_all_reads_are_sanitized_and_private_like_db_fails_closed(app):
    with app.test_client() as c:
        post(c, "/api/import")
        oid = c.get("/api/opportunities").json[0]["id"]
        app.config["APP_MODE"] = "replay"
        for url in [
            "/api/settings",
            "/api/today",
            "/api/messages",
            "/api/opportunities",
            f"/api/opportunities/{oid}",
            "/api/runs",
        ]:
            response = c.get(url)
            assert response.status_code == 200
            assert "SYNTHETIC-CANARY" not in response.text
            assert "collector.demo.invalid" not in response.text
            assert "Upload registry/private" not in response.text
        with connect(app.config["SETTINGS"].db_path) as db, db:
            db.execute("UPDATE messages SET source='private' WHERE id=1")
        assert c.get("/api/messages").status_code == 403


@pytest.mark.parametrize("host", ["localhost:5000", "127.0.0.1:5000"])
def test_allowed_host_with_port(app, host):
    with app.test_client() as c:
        response = c.get("/api/settings", base_url=f"http://{host}")
        assert response.status_code == 200
        assert (
            c.post(
                "/api/settings",
                json={"paused": True},
                base_url=f"http://{host}",
                headers={"X-CSRF-Token": response.json["csrf_token"]},
            ).status_code
            == 200
        )


@pytest.mark.parametrize(
    "url,body",
    [
        ("/api/opportunities/1/status", {"status": []}),
        ("/api/packs/no/status", {"status": []}),
        ("/api/messages/1/category", {"category": []}),
        ("/api/import", {"path": "../../elsewhere"}),
        ("/api/opportunities/999/pack", {"demo": False}),
    ],
)
def test_invalid_mutations(app, url, body):
    with app.test_client() as c:
        assert post(c, url, body).status_code == 400


def test_malformed_json_and_cross_session_csrf(app):
    with app.test_client() as c:
        token = c.get("/api/settings").json["csrf_token"]
        for payload in ["[]", "null", "{"]:
            assert (
                c.post(
                    "/api/import",
                    data=payload,
                    content_type="application/json",
                    headers={"X-CSRF-Token": token},
                ).status_code
                == 400
            )
        assert c.post("/api/import", json={}, headers={"X-CSRF-Token": "\u00e9"}).status_code == 403
    with app.test_client() as other:
        assert (
            other.post("/api/import", json={}, headers={"X-CSRF-Token": token}).status_code == 403
        )


def test_pack_failure_and_fresh_pause_inside_pack(app, monkeypatch):
    from inbound.packs import build
    from inbound.pause import set_paused
    from tests.m3_helpers import opportunity

    with connect(app.config["SETTINGS"].db_path) as db:
        oid = opportunity(db)
    real_rank = build.rank

    def pause_after_rank(*args, **kwargs):
        result = real_rank(*args, **kwargs)
        with connect(app.config["SETTINGS"].db_path) as db:
            set_paused(db, True)
        return result

    monkeypatch.setattr(build, "rank", pause_after_rank)
    with app.test_client() as c:
        assert post(c, f"/api/opportunities/{oid}/pack").status_code == 202
        assert c.get("/api/runs").json[0]["status"] == "paused"
        assert not c.get(f"/api/opportunities/{oid}").json["packs"]
        post(c, "/api/settings", {"paused": False})
        monkeypatch.setattr(build, "rank", real_rank)

        def broken_compile(directory):
            raise RuntimeError("SYNTHETIC-CANARY path secret")

        monkeypatch.setattr(build, "compile_tex", broken_compile)
        post(c, f"/api/opportunities/{oid}/pack")
        run = c.get("/api/runs").json[0]
        assert run["status"] == "failed" and run["pack_id"] is None
        assert "SYNTHETIC-CANARY" not in json.dumps(run)
        assert all(
            p["status"] == "blocked" for p in c.get(f"/api/opportunities/{oid}").json["packs"]
        )


def test_spa_serving_and_traversal(app, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>Synthetic desk</html>")
    (dist / "asset.js").write_text("const demo = true;")
    app.config["WEB_DIST"] = dist
    with app.test_client() as c:
        assert "Synthetic desk" in c.get("/opportunity/1").text
        assert "const demo" in c.get("/asset.js").text
        assert c.get("/api/unknown").status_code == 404
        assert c.get("/../outside").status_code == 404


def test_demo_serve_and_digest_cli_without_listener(tmp_path, monkeypatch, capsys):
    from flask import Flask

    from inbound.__main__ import main
    from inbound.demo import build_demo

    result = build_demo(Settings(data_root=tmp_path))
    assert result["messages"] == 190
    monkeypatch.setenv("INBOUND_DATA_ROOT", str(tmp_path))
    observed = []

    def fake_run(server, **kwargs):
        assert kwargs == {"host": "127.0.0.1", "port": 5000, "debug": False, "use_reloader": False}
        with server.test_client() as c:
            for url in ["/api/settings", "/api/today", "/api/opportunities"]:
                response = c.get(url)
                assert response.status_code == 200
                observed.append(url)

    monkeypatch.setattr(Flask, "run", fake_run)
    assert main(["serve"]) == 0
    assert len(observed) == 3
    assert main(["digest"]) == 0
    assert "Today / Inbox" in capsys.readouterr().out
