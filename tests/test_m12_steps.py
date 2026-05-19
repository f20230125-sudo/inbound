"""Journal publication, privacy and streaming contracts, using fictional records only."""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from inbound.api import create_app
from inbound.db import connect
from inbound.settings import Settings
from inbound.work import execute, start_run
from tests import test_m8_recovery as recovery_tests
from tests import test_m9_gmail as gmail_tests
from tests.m2_helpers import CLOCK
from tests.m3_helpers import opportunity
from tests.test_m8_recovery import upload


@pytest.fixture
def recovery_desk(tmp_path):
    yield from recovery_tests.desk.__wrapped__(tmp_path)


@pytest.fixture
def live(tmp_path):
    return gmail_tests.live.__wrapped__(tmp_path)


def journal(db):
    return [dict(r) for r in db.execute("SELECT * FROM agent_steps ORDER BY id")]


def test_typed_emitter_rollback_append_only_and_dedupe(database):
    from inbound.steps import Classification, Kind, emit

    oid = opportunity(database, "P-D12")
    mid = database.execute(
        "SELECT message_id FROM opportunity_revisions WHERE opportunity_id=?", (oid,)
    ).fetchone()[0]
    before = len(journal(database))
    with pytest.raises(RuntimeError), database:
        emit(
            database,
            Kind.CLASSIFIED,
            Classification("ps_call"),
            entity_type="message",
            entity_id=mid,
            dedupe_key="test:rollback",
        )
        raise RuntimeError("Do not persist this exception or mail text")
    assert len(journal(database)) == before
    with database:
        first = emit(
            database,
            Kind.CLASSIFIED,
            Classification("ps_call"),
            entity_type="message",
            entity_id=mid,
            dedupe_key="test:retry",
        )
        assert (
            emit(
                database,
                Kind.CLASSIFIED,
                Classification("ps_call"),
                entity_type="message",
                entity_id=mid,
                dedupe_key="test:retry",
            )
            == first
        )
    for sql in ("UPDATE agent_steps SET actor='system'", "DELETE FROM agent_steps"):
        with pytest.raises(sqlite3.IntegrityError):
            database.execute(sql)
    with pytest.raises(ValueError):
        emit(
            database,
            Kind.CLASSIFIED,
            Classification("mail text"),
            entity_type="message",
            entity_id=mid,
        )
    with pytest.raises(ValueError):
        emit(database, Kind.CLASSIFIED, {"body": "secret"}, entity_type="message", entity_id=mid)


@pytest.mark.parametrize("race", ["event", "content", "pause", "same_connection"])
def test_staged_import_generation_and_pause(tmp_path, monkeypatch, race):
    from inbound import work
    from inbound.pause import set_paused
    from inbound.steps import Empty, Kind, emit

    settings = Settings(data_root=tmp_path)
    with connect(settings.db_path) as db:
        rid = start_run(db, "import", source_type="export")
    triage = work.triage_messages

    def concurrent(staged, **kwargs):
        result = triage(staged, **kwargs)
        with connect(settings.db_path) as live:
            if race == "event":
                emit(live, Kind.GMAIL_STARTED, Empty(), source="synthetic")
            elif race == "pause":
                set_paused(live, True)
            else:
                live.execute("INSERT INTO settings VALUES ('changed','1')")
        return result

    if race == "same_connection":
        original = work.stage

        def stage(db, run_id, name):
            original(db, run_id, name)
            if name == "triage":
                with db:
                    db.execute("INSERT INTO settings VALUES ('changed','1')")

        monkeypatch.setattr(work, "stage", stage)
    else:
        monkeypatch.setattr(work, "triage_messages", concurrent)
    execute(settings, rid, "import", root=Path("fixtures/export_sample"), clock=lambda: CLOCK)
    with connect(settings.db_path) as db:
        status = db.execute("SELECT status FROM runs WHERE id=?", (rid,)).fetchone()[0]
        assert status == {"event": "success", "pause": "paused"}.get(race, "failed")
        rows = journal(db)
        assert any(r["phase"] == "progress" for r in rows)
        if race != "event":
            assert not db.execute("SELECT 1 FROM snapshots").fetchone()
            assert not any(r["outcome"] == "succeeded" for r in rows)
        else:
            assert any(r["kind"] == "snapshot.published" for r in rows)
            assert len({r["id"] for r in rows}) == len(rows)


def test_failed_import_has_progress_failure_and_no_result(tmp_path, monkeypatch):
    from inbound import work

    settings = Settings(data_root=tmp_path)
    with connect(settings.db_path) as db:
        rid = start_run(db, "import", source_type="export")

    def broken(*args, **kwargs):
        raise ValueError("PRIVATE EXCEPTION CONTENT")

    monkeypatch.setattr(work, "extract_messages", broken)
    execute(settings, rid, "import", root=Path("fixtures/export_sample"))
    with connect(settings.db_path) as db:
        rows = journal(db)
        assert any(r["kind"] == "import.failed" for r in rows)
        assert any(json.loads(r["facts_json"]).get("stage") == "triage" for r in rows)
        assert not any(r["outcome"] == "succeeded" for r in rows)
        assert "PRIVATE EXCEPTION CONTENT" not in json.dumps(rows)
        assert not db.execute("SELECT 1 FROM messages").fetchone()


def test_steps_resume_heartbeat_origin_replay_and_read_only(tmp_path):
    from inbound.steps import Empty, Kind, emit

    settings = Settings(data_root=tmp_path)
    app = create_app({"TESTING": True, "SETTINGS": settings, "AGENT_HEARTBEAT": 0})
    with connect(settings.db_path) as db, db:
        private = emit(db, Kind.GMAIL_STARTED, Empty(), source="private")
        public = emit(db, Kind.GMAIL_STARTED, Empty(), source="synthetic")
    client = app.test_client()
    assert client.get("/api/agent/steps?after=-1").status_code == 400
    assert client.get("/api/agent/steps?after=mail").status_code == 400
    rows = client.get(f"/api/agent/steps?after={private}").json["steps"]
    assert [r["id"] for r in rows] == [public]
    assert rows[0]["text"].startswith("I ")
    response = client.get(
        "/api/agent/stream", headers={"Last-Event-ID": str(private)}, buffered=False
    )
    chunks = iter(response.response)
    first = next(chunks).decode()
    assert f"id: {public}\n" in first and f"id: {private}\n" not in first
    assert ": heartbeat" in next(chunks).decode()
    response.close()
    assert (
        client.get("/api/agent/stream", headers={"Origin": "https://untrusted.invalid"}).status_code
        == 403
    )
    assert (
        client.get("/api/agent/stream", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    )
    app.config["APP_MODE"] = "replay"
    with connect(settings.db_path) as db:
        before = db.total_changes
        saved = journal(db)
        replay = client.get("/api/agent/steps?replay=last").json
        assert all(r["source"] == "synthetic" for r in replay["steps"])
        assert private not in [r["id"] for r in replay["steps"]]
        assert replay["label"].startswith("Recorded check - ")
        assert client.get("/api/agent/steps").json["steps"][0]["id"] == public
        response = client.get("/api/agent/stream", buffered=False)
        assert f"id: {private}\n" not in next(iter(response.response)).decode()
        response.close()
        assert journal(db) == saved and db.total_changes == before


def test_recorded_replay_is_pinned_while_another_check_starts(tmp_path):
    from inbound.steps import Empty, Kind, emit

    settings = Settings(data_root=tmp_path)
    with connect(settings.db_path) as db:
        first = start_run(db, "import", source_type="export", source_provenance="synthetic")
        for _ in range(110):
            emit(db, Kind.GMAIL_STARTED, Empty(), run_id=first, source="synthetic")
        db.execute("UPDATE runs SET status='success' WHERE id=?", (first,))
    c = create_app({"TESTING": True, "SETTINGS": settings}).test_client()
    page = c.get("/api/agent/steps?replay=last").json
    assert page["has_more"]
    recording_id, through = page["recording_id"], page["through"]
    with connect(settings.db_path) as db:
        start_run(db, "import", source_type="export", source_provenance="synthetic")
    next_page = c.get(
        f"/api/agent/steps?replay={recording_id}&through={through}&after={page['after']}"
    ).json
    assert next_page["steps"] and all(s["run_id"] == first for s in next_page["steps"])
    assert next_page["label"] == page["label"]


def test_unsorted_mail_is_one_group_with_separate_briefing(database):
    from inbound.agent import agent_state
    from inbound.db import import_messages
    from inbound.triage.rules import triage_messages
    from tests.m2_helpers import message

    opportunity(database, "P-D12")
    import_messages(
        database,
        [
            replace(
                message("P-D12"),
                provider_id=f"sorting-{i}",
                thread_id=f"sorting-{i}",
                sender="unknown@fiction.invalid",
                subject="Hello",
            )
            for i in range(7)
        ],
    )
    triage_messages(database)
    state = agent_state(database, CLOCK)
    text = " ".join(c["text"] for c in state["briefing"])
    assert "1 call needs you." in text and "7 emails need sorting." in text
    groups = [d for d in state["decisions"] if d["id"] == "sorting-backlog"]
    assert len(groups) == 1 and "7" in groups[0]["title"]
    assert not any(d["id"].startswith("message-") for d in state["decisions"])


def test_publish_transaction_rolls_back_domain_and_results(tmp_path):
    settings = Settings(data_root=tmp_path)
    with connect(settings.db_path) as db:
        rid = start_run(db, "import", source_type="export")
        db.execute(
            "CREATE TRIGGER reject_publication BEFORE INSERT ON agent_steps "
            "WHEN NEW.kind='snapshot.published' BEGIN SELECT RAISE(ABORT,'injected'); END"
        )
    execute(settings, rid, "import", root=Path("fixtures/export_sample"))
    with connect(settings.db_path) as db:
        assert not db.execute("SELECT 1 FROM messages").fetchone()
        assert not db.execute("SELECT 1 FROM snapshots").fetchone()
        assert not any(s["outcome"] == "succeeded" for s in journal(db))
        assert journal(db)[-1]["kind"] == "import.failed"


def test_content_generation_rolls_back_and_excludes_telemetry(database):
    from inbound.steps import Empty, Kind, emit

    def generation():
        return database.execute("SELECT generation FROM domain_generation").fetchone()[0]

    before = generation()
    with database:
        emit(database, Kind.GMAIL_STARTED, Empty())
        database.execute(
            "INSERT INTO runs(kind,started_at,status) VALUES ('triage',?,'running')",
            (CLOCK.isoformat(),),
        )
    assert generation() == before
    with pytest.raises(RuntimeError), database:
        database.execute("INSERT INTO settings VALUES ('rollback','1')")
        assert generation() > before
        raise RuntimeError("rollback")
    assert generation() == before


def test_emitter_cannot_downgrade_private_references_or_claim_failed_ready(database):
    from inbound.steps import Empty, Kind, Verification, emit

    oid = opportunity(database, "P-D12")
    with database:
        database.execute("UPDATE messages SET source='private'")
    with pytest.raises(ValueError):
        emit(
            database,
            Kind.READY,
            Verification(False, False),
            entity_type="opportunity",
            entity_id=oid,
        )
    with database:
        identity = emit(
            database,
            Kind.CREATED,
            Empty(),
            entity_type="opportunity",
            entity_id=oid,
            source="synthetic",
        )
    assert (
        database.execute("SELECT source FROM agent_steps WHERE id=?", (identity,)).fetchone()[0]
        == "private"
    )


def test_fetch_narration_does_not_hide_oversize_mail(database):
    from inbound.steps import Fetch, Kind, emit, page

    with database:
        emit(database, Kind.GMAIL_FETCHED, Fetch(1, 0, 1), source="synthetic")
    text = page(database)["steps"][0]["text"]
    assert "No new messages" not in text
    assert "1 message" in text and "size limit" in text


def test_interruption_recorded_once_without_resumption(database):
    from inbound.work import interrupt_runs

    rid = start_run(database, "import", source_type="export")
    interrupt_runs(database)
    interrupt_runs(database)
    rows = [s for s in journal(database) if s["kind"] == "work.interrupted"]
    assert len(rows) == 1 and rows[0]["outcome"] == "cancelled"
    assert rows[0]["run_id"] == rid
    assert not database.execute("SELECT 1 FROM runs WHERE status='running'").fetchone()


def test_watch_startup_records_interrupted_work(tmp_path, monkeypatch):
    from inbound.__main__ import main
    from inbound.gmail_sync import Poller

    settings = Settings(data_root=tmp_path)
    with connect(settings.db_path) as db:
        start_run(db, "import", source_type="export", source_provenance="synthetic")
    monkeypatch.setattr(Settings, "from_env", lambda: settings)

    def watch(poller):
        with connect(settings.db_path) as db:
            assert journal(db)[-1]["kind"] == "work.interrupted"
        raise KeyboardInterrupt

    monkeypatch.setattr(Poller, "run", watch)
    assert main(["watch"]) == 0


def test_gmail_hooks_are_correlated_and_private(live):
    from inbound import gmail_sync

    settings, fake = live
    gmail_sync.sync(settings, transport=fake.transport())
    with connect(settings.db_path) as db:
        rows = journal(db)
        kinds = {s["kind"] for s in rows}
        assert {
            "gmail.started",
            "gmail.fetched",
            "gmail.finished",
            "snapshot.published",
            "triage.classified",
            "opportunity.created",
        } <= kinds
        assert len({s["correlation_id"] for s in rows}) == 1
        assert all(s["source"] == "private" for s in rows)
        assert not any("Harbor Finch" in s["facts_json"] for s in rows)
    gmail_sync.sync(settings, transport=fake.transport())
    app = create_app({"TESTING": True, "SETTINGS": settings})
    replay = app.test_client().get("/api/agent/steps?replay=last").json
    assert any(s["text"] == "I checked Gmail. No new messages." for s in replay["steps"])


def test_gmail_failure_stores_no_exception_text(live, monkeypatch):
    from inbound import gmail_sync

    settings, _ = live

    def fail(*args):
        raise ValueError("mail contents must never be journaled")

    monkeypatch.setattr(gmail_sync, "fetch_new", fail)
    with pytest.raises(ValueError):
        gmail_sync.sync(settings)
    with connect(settings.db_path) as db:
        rows = journal(db)
        assert [s["kind"] for s in rows] == ["gmail.started", "gmail.failed"]
        assert "mail contents" not in json.dumps(rows)


def test_user_action_hooks_and_correction_transaction(tmp_path, monkeypatch):
    from inbound import api
    from inbound.application_activity import record

    settings = Settings(data_root=tmp_path)
    with connect(settings.db_path) as db:
        oid = opportunity(db, "P-D12")
        rev = db.execute(
            "SELECT * FROM opportunity_revisions WHERE opportunity_id=?", (oid,)
        ).fetchone()
        activity = record(
            db,
            oid,
            applied_at=CLOCK.isoformat(),
            human_submission=True,
            expected_revision_id=rev["id"],
            expected_activity_id=None,
            note="PRIVATE NOTE",
        )
        assert (
            record(
                db,
                oid,
                applied_at=CLOCK.isoformat(),
                human_submission=True,
                expected_revision_id=rev["id"],
                expected_activity_id=None,
                note="PRIVATE NOTE",
            )
            == activity
        )
        assert len([s for s in journal(db) if s["kind"] == "action.applied_outside"]) == 1
        assert "PRIVATE NOTE" not in json.dumps(journal(db))
    app = create_app({"TESTING": True, "SETTINGS": settings})
    c = app.test_client()
    token = c.get("/api/settings").json["csrf_token"]
    headers = {"X-CSRF-Token": token}
    assert (
        c.post(
            f"/api/opportunities/{oid}/status",
            json={"status": "skipped", "reason": "PRIVATE REASON"},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        c.post(
            f"/api/opportunities/{oid}/status", json={"status": "undo_skip"}, headers=headers
        ).status_code
        == 200
    )
    mid = rev["message_id"]
    assert (
        c.post(
            f"/api/messages/{mid}/category", json={"category": "needs_review"}, headers=headers
        ).status_code
        == 200
    )
    with connect(settings.db_path) as db:
        rows = journal(db)
        actions = [s for s in rows if s["actor"] == "uzair"]
        assert len(actions) == 4
        assert "PRIVATE REASON" not in json.dumps(rows)
    original = api.emit

    def fail(*args, **kwargs):
        raise ValueError("Injected journal failure")

    monkeypatch.setattr(api, "emit", fail)
    assert (
        c.post(
            f"/api/messages/{mid}/category", json={"category": "academic"}, headers=headers
        ).status_code
        == 400
    )
    monkeypatch.setattr(api, "emit", original)
    with connect(settings.db_path) as db:
        assert (
            db.execute(
                "SELECT corrected_category FROM triage WHERE message_id=?", (mid,)
            ).fetchone()[0]
            == "needs_review"
        )


def test_attachment_hook_is_atomic_and_preview_is_read_only(recovery_desk, monkeypatch):
    from inbound import attachment_recovery

    app, _, _, _, _ = recovery_desk
    settings = app.config["SETTINGS"]
    with connect(settings.db_path) as db:
        before = journal(db)
    preview = upload(recovery_desk).json
    with connect(settings.db_path) as db:
        assert journal(db) == before
    original = attachment_recovery.emit
    monkeypatch.setattr(
        attachment_recovery,
        "emit",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("Injected failure")),
    )
    assert upload(recovery_desk, action="confirm", preview=preview).status_code == 400
    with connect(settings.db_path) as db:
        assert not db.execute("SELECT 1 FROM attachment_recoveries").fetchone()
        assert journal(db) == before
    monkeypatch.setattr(attachment_recovery, "emit", original)
    assert upload(recovery_desk, action="confirm", preview=preview).status_code == 200
    assert upload(recovery_desk, action="confirm", preview=preview).status_code == 200
    with connect(settings.db_path) as db:
        rows = [s for s in journal(db) if s["kind"] == "action.attachment_recovered"]
        assert len(rows) == 1 and rows[0]["actor"] == "uzair"


@pytest.mark.parametrize("passed", [True, False])
def test_pack_verification_result_is_atomic(database, monkeypatch, passed):
    from inbound.packs import build

    oid = opportunity(database, "P-D12")
    if not passed:
        monkeypatch.setattr(build, "verify", lambda *a: {"passed": False})
    if passed:
        build.create_pack(database, oid, demo=True)
    else:
        with pytest.raises(RuntimeError):
            build.create_pack(database, oid, demo=True)
    rows = journal(database)
    verified = [s for s in rows if s["kind"] == "pack.verified"]
    assert len(verified) == 1
    assert json.loads(verified[0]["facts_json"])["passed"] is passed
    assert bool([s for s in rows if s["kind"] == "pack.ready"]) is passed
    assert bool([s for s in rows if s["kind"] == "pack.failed"]) is not passed
    assert all(
        s["entity_id"] == database.execute("SELECT id FROM packs").fetchone()[0]
        for s in rows
        if s["kind"].startswith("pack.")
    )


def test_bounded_catch_up_and_live_id_allocation(tmp_path, monkeypatch):
    from inbound import work
    from inbound.steps import Empty, Kind, emit

    settings = Settings(data_root=tmp_path)
    with connect(settings.db_path) as db:
        rid = start_run(db, "import", source_type="export", source_provenance="synthetic")
    triage = work.triage_messages
    concurrent_ids = []

    def events(staged, **kwargs):
        result = triage(staged, **kwargs)
        with connect(settings.db_path) as live:
            for _ in range(7):
                concurrent_ids.append(emit(live, Kind.GMAIL_STARTED, Empty(), source="private"))
        return result

    monkeypatch.setattr(work, "triage_messages", events)
    execute(settings, rid, "import", root=Path("fixtures/export_sample"))
    c = create_app({"TESTING": True, "SETTINGS": settings}).test_client()
    after = 0
    steps = []
    more = True
    while more:
        result = c.get(f"/api/agent/steps?after={after}").json
        assert len(result["steps"]) <= 100
        assert all(s["id"] > after for s in result["steps"])
        steps += result["steps"]
        after, more = result["after"], result["has_more"]
    assert len({s["id"] for s in steps}) == len(steps) > 100
    assert set(concurrent_ids) <= {s["id"] for s in steps}
    assert min(s["id"] for s in steps if s["kind"] == "triage.classified") > max(concurrent_ids)
    tail = c.get("/api/agent/steps").json
    assert len(tail["steps"]) == 100 and not tail["has_more"]
    assert tail["steps"][-1]["id"] == steps[-1]["id"]
    with connect(settings.db_path) as db:
        assert len(steps) == len(journal(db))


def test_alert_journal_has_guards_and_precise_delivery_wording(tmp_path):
    from inbound.pause import set_paused

    settings = Settings(data_root=tmp_path)
    with connect(settings.db_path) as db:
        oid = opportunity(db, "P-D12")
    app = create_app({"TESTING": True, "SETTINGS": settings})
    c = app.test_client()
    token = c.get("/api/settings").json["csrf_token"]
    value = {
        "opportunity_id": oid,
        "kind": "requested",
        "alert_type": "new_call",
        "reason": "requested",
    }
    assert c.post("/api/agent/alerts", json=value).status_code == 403
    headers = {"X-CSRF-Token": token}
    assert c.post("/api/agent/alerts", json=value, headers=headers).status_code == 200
    line = c.get("/api/agent/steps").json["steps"][-1]["text"]
    assert "requested" in line and "unknown" in line and "saw" not in line
    with connect(settings.db_path) as db:
        set_paused(db, True)
    assert c.post("/api/agent/alerts", json=value, headers=headers).status_code == 409
    app.config["APP_MODE"] = "replay"
    assert c.post("/api/agent/alerts", json=value, headers=headers).status_code == 405
