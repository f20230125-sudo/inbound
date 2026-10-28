"""Scout reports stored facts only; synthetic data, no work on reads."""

import json
from datetime import timedelta

import pytest

from inbound.agent import agent_state, mood
from inbound.digest import today
from tests.m2_helpers import CLOCK
from tests.m3_helpers import opportunity


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        ({}, "idle"),
        ({"working": True}, "working"),
        ({"decisions": 1}, "needs_decision"),
        ({"drafts": 1}, "draft_ready"),
        ({"failed": True}, "failed"),
        ({"paused": True}, "paused"),
        ({"connected": False}, "disconnected"),
        ({"paused": True, "working": True, "failed": True}, "paused"),
        ({"working": True, "failed": True, "decisions": 2}, "working"),
        ({"failed": True, "decisions": 2}, "failed"),
        ({"decisions": 1, "drafts": 1}, "needs_decision"),
    ],
)
def test_mood(facts, expected):
    assert mood(**facts) == expected


def test_empty_and_unknown_freshness(database):
    state = agent_state(database, CLOCK)
    assert state["mood"] == "idle"
    assert (
        state["briefing"][0]["text"]
        == "I don't have a recent successful check. New mail may be missing."
    )
    assert state["counts"] == {"decisions": 0, "drafts": 0}
    assert not state["decisions"]
    assert not any("0" in line["text"] for line in state["briefing"])
    assert today(database, CLOCK)["decision_queue"] == []
    assert today(database, CLOCK)["past_deadlines"] == []


def test_queue_expiry_uncertainty_and_reopening(database):
    expired = opportunity(database, "P-D06")
    urgent = opportunity(database, "P-D12")
    unknown = opportunity(database, "P-D10")
    blocked = opportunity(database, "P-D16")
    result = today(database, CLOCK)
    active = [e["id"] for e in result["decision_queue"] if e["kind"] == "call"]
    assert active.index(urgent) < active.index(unknown)
    assert blocked in active and unknown in active and expired not in active
    assert expired in [e["id"] for e in result["past_deadlines"]]
    assert (
        database.execute("SELECT status FROM opportunities WHERE id=?", (expired,)).fetchone()[0]
        != "skipped"
    )
    assert all("decision_priority" in e and "fit" not in e for e in result["decision_queue"])
    # Recompute using supported evidence at an earlier clock: expired is not a stored status.
    before = today(database, CLOCK - timedelta(days=4))
    assert expired in [e["id"] for e in before["decision_queue"]]


def test_conflicting_old_candidate_never_becomes_expired(database):
    opportunity(database, "J09")
    result = today(database, CLOCK + timedelta(days=365))
    assert result["uncertain_deadlines"]
    assert result["decision_queue"]
    assert not result["past_deadlines"]


def test_numbers_trace_to_current_rows_and_ready_drafts(database):
    oid = opportunity(database, "P-D12")
    opportunity(database, "P-D06")
    rev = database.execute(
        "SELECT id FROM opportunity_revisions WHERE opportunity_id=?", (oid,)
    ).fetchone()[0]
    with database:
        database.execute("INSERT INTO snapshots(imported_at) VALUES (?)", (CLOCK.isoformat(),))
        database.execute(
            "INSERT INTO packs(id,opportunity_id,revision_id,status,checks_json,created_at,demo) "
            "VALUES ('m11-draft',?,?,'needs_review',?, ?,1)",
            (oid, rev, json.dumps({"passed": True}), CLOCK.isoformat()),
        )
    state = agent_state(database, CLOCK)
    assert state["counts"] == {"decisions": 1, "drafts": 1}
    assert state["mood"] == "draft_ready"
    assert state["decisions"][0]["action"] == "Review draft"
    assert "1 call needs you." in [b["text"] for b in state["briefing"]]
    assert "1 draft is ready for review." in [b["text"] for b in state["briefing"]]
    assert all(b["href"] for b in state["briefing"])
    # A stale content version must never be called a ready draft.
    with database:
        database.execute(
            "UPDATE opportunities SET content_version=content_version+1 WHERE id=?", (oid,)
        )
    assert agent_state(database, CLOCK)["counts"]["drafts"] == 0


def test_recent_zero_and_gmail_failure_do_not_invent_success(database):
    with database:
        database.execute("INSERT INTO snapshots(imported_at) VALUES (?)", (CLOCK.isoformat(),))
    state = agent_state(database, CLOCK)
    assert "There is no actionable work in this snapshot." in [b["text"] for b in state["briefing"]]
    assert not any("Gmail" in b["text"] for b in state["briefing"])
    gmail = {
        "last_sync_at": CLOCK.isoformat(),
        "last_error": "Failure",
        "next_check_at": CLOCK.isoformat(),
    }
    failed = agent_state(database, CLOCK, gmail=gmail)
    assert failed["mood"] == "failed"
    assert "failed" in failed["briefing"][0]["text"]
    assert failed["freshness"]["gmail_success_at"] is None
    assert failed["freshness"]["next_check_at"] is None  # past schedules aren't future promises


def test_gmail_schedule_pause_and_work_are_independent(database):
    gmail = {
        "last_sync_at": CLOCK.isoformat(),
        "last_result": {"status": "success"},
        "connected": True,
        "next_check_at": (CLOCK + timedelta(minutes=2)).isoformat(),
    }
    state = agent_state(database, CLOCK, gmail=gmail, syncing=True)
    assert state["mood"] == "working" and state["working"]
    assert state["freshness"]["gmail_success_at"] == CLOCK.isoformat()
    assert state["freshness"]["next_check_at"] == gmail["next_check_at"]
    with database:
        database.execute("UPDATE settings SET value='1' WHERE key='paused'")
    state = agent_state(database, CLOCK, gmail=gmail, syncing=True)
    assert state["mood"] == "paused" and state["working"]
    assert state["freshness"]["next_check_at"] is None


def test_read_endpoint_guards_no_jobs_and_replay(tmp_path):
    from inbound.api import create_app
    from inbound.settings import Settings

    settings = Settings(data_root=tmp_path)
    for mode in ("local", "replay"):
        app = create_app(
            {"TESTING": True, "SETTINGS": settings, "APP_MODE": mode, "CLOCK": lambda: CLOCK}
        )
        with app.test_client() as client:
            assert client.get("/api/agent/state").status_code == 200
            assert (
                client.get("/api/agent/state", headers={"Host": "outside.invalid"}).status_code
                == 403
            )
            assert client.post("/api/agent/state", json={}).status_code in {403, 405}
            assert client.get("/api/runs").json == []


def test_failed_check_without_a_snapshot_does_not_claim_one(database):
    state = agent_state(database, CLOCK, gmail={"last_error": "Unavailable"})
    assert "No successful snapshot is recorded." in state["briefing"][0]["text"]
    assert "previous snapshot is still available" not in state["briefing"][0]["text"]


def test_run_state_and_briefing_are_from_the_actual_ledger(database):
    with database:
        database.execute("INSERT INTO snapshots(imported_at) VALUES (?)", (CLOCK.isoformat(),))
        database.execute(
            "INSERT INTO runs(kind,status,started_at,stage) VALUES ('import','running',?,'triage')",
            (CLOCK.isoformat(),),
        )
    state = agent_state(database, CLOCK)
    assert state["mood"] == "working"
    assert state["status"] == "I'm classifying saved messages."
    with database:
        database.execute("UPDATE runs SET status='failed',finished_at=?", (CLOCK.isoformat(),))
    state = agent_state(database, CLOCK)
    assert state["mood"] == "failed"
    assert (
        state["briefing"][0]["text"]
        == "My latest local run failed. Your previous snapshot is still available."
    )


def test_evidence_backed_amendment_returns_an_expired_call(database):
    from dataclasses import replace

    from inbound.db import import_messages
    from inbound.extract.pipeline import extract_messages
    from inbound.triage.rules import triage_messages
    from tests.m2_helpers import message

    oid = opportunity(database, "P-D06")
    assert oid in [e["id"] for e in today(database, CLOCK)["past_deadlines"]]
    amendment = replace(
        message("P-D06"),
        provider_id="m11-reopened",
        sent_at=CLOCK,
        received_at=CLOCK,
        body_text="Revised deadline: 30 October 2026, 08:00AM",
    )
    import_messages(database, [amendment])
    triage_messages(database)
    extract_messages(database, clock=lambda: CLOCK)
    result = today(database, CLOCK)
    assert oid in [e["id"] for e in result["decision_queue"]]
    assert oid not in [e["id"] for e in result["past_deadlines"]]
