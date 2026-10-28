"""Release contracts use only fictional mail and the local Flask client."""

from contextlib import closing
from datetime import UTC, datetime

from inbound.db import connect
from inbound.pause import set_paused
from tests.test_api import app as app_fixture
from tests.test_api import post

app = app_fixture


def test_scout_open_deadlines_sort_by_time_across_weekdays(database, monkeypatch):
    from inbound import scout

    values = ["2026-10-30T08:00:00+04:00", "2026-10-29T10:00:00+04:00",
              "2026-10-29T08:00:00+04:00", "2026-10-31T08:00:00+04:00"]
    calls = [{"id": index, "status": "new", "company": f"Fictional {index}",
              "revision_id": index, "fields": {"deadline": {"status": "found", "normalized": value}}}
             for index, value in enumerate(values, 1)]
    monkeypatch.setattr(scout, "opportunities", lambda *args: calls)
    monkeypatch.setattr(scout.citations, "revision", lambda *args: None)
    result = scout.due(database, datetime(2026, 10, 28, 6, tzinfo=UTC), False)
    assert [entry["text"].split(": ")[0] for entry in result["groups"]["timed"]] == [
        "Fictional 3", "Fictional 2", "Fictional 1", "Fictional 4",
    ]


def test_message_summaries_do_not_select_or_transfer_bodies(app):
    with app.test_client() as client:
        post(client, "/api/import")
        with closing(connect(app.config["SETTINGS"].db_path)) as db:
            mid = db.execute("SELECT id FROM messages ORDER BY id LIMIT 1").fetchone()[0]
            db.execute("UPDATE messages SET body_text=? WHERE id=?", ("BODY-SENTINEL" * 20000, mid))
            db.commit()
        response = client.get("/api/messages")
        assert response.status_code == 200
        assert b"BODY-SENTINEL" not in response.data
        assert all("body_text" not in message for message in response.json)
        assert client.get("/api/messages?category=ps_call").json
        with closing(connect(app.config["SETTINGS"].db_path)) as db:
            from inbound.api.data import messages

            statements = []
            db.set_trace_callback(statements.append)
            messages(db)
            assert all("body_text" not in sql.lower() for sql in statements)


def test_source_detail_is_exact_read_only_available_paused_and_host_guarded(app):
    with app.test_client() as client:
        post(client, "/api/import")
        with closing(connect(app.config["SETTINGS"].db_path)) as db:
            original = dict(db.execute("SELECT * FROM messages ORDER BY id LIMIT 1").fetchone())
            set_paused(db, True)
            before = "\n".join(db.iterdump())
        url = f"/api/messages/{original['id']}"
        detail = client.get(url)
        assert detail.status_code == 200
        assert detail.json == {key: original[key] for key in (
            "id", "provider_id", "subject", "sender", "sent_at", "body_text", "body_complete",
            "source",
        )}
        assert detail.headers["Cache-Control"] == "no-store"
        assert client.get(url, headers={"Host": "evil.invalid"}).status_code == 403
        assert client.get("/api/messages/999999").status_code == 404
        assert client.post(url, json={}).status_code == 403
        with closing(connect(app.config["SETTINGS"].db_path)) as db:
            assert "\n".join(db.iterdump()) == before


def test_source_detail_keeps_replay_sanitization_and_private_database_exclusion(app):
    with app.test_client() as client:
        post(client, "/api/import")
        with closing(connect(app.config["SETTINGS"].db_path)) as db:
            mid = db.execute("SELECT id FROM messages ORDER BY id LIMIT 1").fetchone()[0]
            db.execute("UPDATE messages SET body_text=? WHERE id=?",
                       ("Fictional source\nSYNTHETIC-CANARY\nsecret=hidden", mid))
            db.commit()
        app.config["APP_MODE"] = "replay"
        response = client.get(f"/api/messages/{mid}")
        assert response.status_code == 200
        assert response.json["body_text"] == "Fictional source"
        with closing(connect(app.config["SETTINGS"].db_path)) as db:
            db.execute("UPDATE messages SET source='private' WHERE id=?", (mid,))
            db.commit()
        assert client.get(f"/api/messages/{mid}").status_code == 403
