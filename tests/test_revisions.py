import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from inbound.db import import_messages
from inbound.extract.pipeline import extract_messages
from inbound.pause import PausedError, set_paused
from inbound.sources.export_txt import load
from inbound.triage.rules import triage_messages
from tests.m2_helpers import CLOCK, message


def run(db, messages):
    import_messages(db, messages)
    triage_messages(db)
    return extract_messages(db, clock=lambda: CLOCK)


@pytest.mark.parametrize(
    "anchor,reminder", [("P-D01", "P-D07"), ("P-D02", "P-D08"), ("P-D03", "P-D09")]
)
def test_matching_and_amendment(database, anchor, reminder):
    run(database, [message(reminder), message(anchor)])
    assert database.execute("SELECT count(*) FROM opportunities").fetchone()[0] == 1
    rows = database.execute("SELECT * FROM opportunity_revisions ORDER BY id").fetchall()
    assert len(rows) == 2
    effective = json.loads(rows[-1]["fields_json"])
    assert effective["deadline"]["status"] == "inferred"
    assert effective["form_link"]["normalized"].endswith(anchor)
    assert extract_messages(database)["revisions"] == 0


def test_conflicting_quotes_and_review_invalidation(database):
    original = message("P-D01")
    run(database, [original])
    database.execute("INSERT INTO packs(id,opportunity_id,status,created_at) "
                     "VALUES('1',1,'reviewed','2026-10-28')")
    database.commit()
    newer = replace(
        original,
        provider_id="amendment",
        sent_at=original.sent_at + timedelta(hours=2),
        body_text="CV Submission Deadline: 29 October 2026, 08:00AM",
    )
    run(database, [newer])
    assert database.execute("SELECT status FROM packs").fetchone()[0] == "needs_review"
    field = json.loads(
        database.execute(
            "SELECT fields_json FROM opportunity_revisions ORDER BY id DESC"
        ).fetchone()[0]
    )["deadline"]
    assert field["status"] == "conflicting" and field["normalized"] is None
    assert len(field["candidates"]) == 2
    assert all(c["source_text"] and c["provenance"]["message_id"] for c in field["candidates"])


def test_company_only_suggestion_and_blocker(database):
    run(database, [message("P-D01"), message("P-D04"), message("P-D17")])
    assert database.execute("SELECT count(*) FROM opportunities").fetchone()[0] == 3
    assert database.execute("SELECT count(*) FROM merge_suggestions").fetchone()[0] >= 1
    assert database.execute(
        "SELECT blocked_reason FROM opportunities WHERE status='blocked'"
    ).fetchone()[0]


def test_admin_no_opportunity_and_urgency(database):
    run(database, [message("P-D21"), message("P-D22"), message("P-D23")])
    assert database.execute("SELECT count(*) FROM opportunities").fetchone()[0] == 0
    assert database.execute("SELECT count(*) FROM message_extractions").fetchone()[0] == 3
    assert database.execute("SELECT count(*) FROM triage WHERE urgency='high'").fetchone()[0] == 2


def test_late_import_retains_sent_order_and_effective_amendment(database):
    run(database, [message("P-D07")])
    run(database, [message("P-D01")])
    from inbound.extract.pipeline import opportunity_state

    state = opportunity_state(database, 1, clock=lambda: CLOCK)
    assert state["fields"]["deadline"]["status"] == "inferred"
    assert state["fields"]["deadline"]["provenance"]["message_id"] == "P-D07"
    assert state["fields"]["form_link"]["provenance"]["message_id"] == "P-D01"
    assert state["expired"] is False


def test_missing_deadline_has_unknown_expiry(database):
    run(database, [message("P-D10")])
    from inbound.extract.pipeline import opportunity_state

    assert opportunity_state(database, 1, clock=lambda: CLOCK)["expired"] is None


def test_non_deadline_extension_does_not_authorize_supersession(database):
    original = message("P-D01")
    run(database, [original])
    newer = replace(
        original,
        provider_id="unqualified",
        sent_at=original.sent_at + timedelta(hours=1),
        body_text="Expected Skills: database extension development\n"
        "CV Submission Deadline: 29 October 2026, 08:00AM",
    )
    run(database, [newer])
    from inbound.extract.pipeline import opportunity_state

    assert opportunity_state(database, 1)["fields"]["deadline"]["status"] == "conflicting"


def test_quoted_relative_retains_older_anchor_in_conflict(database):
    original = replace(message("P-D01"), body_text="Deadline: tomorrow at 08:00AM")
    run(database, [original])
    newer = replace(
        original,
        provider_id="next-day",
        sent_at=original.sent_at + timedelta(days=1),
        body_text="Deadline: 29 October 2026, 08:00AM\n--- Original message ---\n"
        "> Deadline: tomorrow at 08:00AM",
    )
    run(database, [newer])
    from inbound.extract.pipeline import opportunity_state

    deadline = opportunity_state(database, 1)["fields"]["deadline"]
    assert deadline["status"] == "conflicting"
    assert {c["normalized"] for c in deadline["candidates"]} == {
        "2026-10-28T08:00:00+04:00",
        "2026-10-29T08:00:00+04:00",
    }
    assert deadline["candidates"][0]["anchor"] == original.sent_at.isoformat()


def test_identical_subject_with_different_links_suggests_separate_calls(database):
    original = message("P-D01")
    same_subject = replace(
        original,
        provider_id="new-link",
        thread_id="different-thread",
        body_text=original.body_text.replace(
            "SYNTHETIC-NOT-LIVE-P-D01", "SYNTHETIC-NOT-LIVE-example"
        ),
    )
    run(database, [original, same_subject])
    assert database.execute("SELECT count(*) FROM opportunities").fetchone()[0] == 2
    suggestion = database.execute("SELECT * FROM merge_suggestions").fetchone()
    assert suggestion["reason"] == "same_subject_different_link"
    assert suggestion["opportunity_id"] != suggestion["candidate_id"]
    links = [
        json.loads(r[0])["form_link"]
        for r in database.execute("SELECT fields_json FROM opportunity_revisions")
    ]
    assert all(link["status"] == "found" for link in links)
    assert len({link["normalized"] for link in links}) == 2


@pytest.mark.parametrize("joining", ["thread", "link", "subject_without_link"])
def test_grouping_joining_evidence(database, joining):
    original = message("P-D01")
    newer = replace(
        original,
        provider_id="joining",
        thread_id=original.thread_id if joining == "thread" else "another-thread",
        subject="Re: " + original.subject if joining != "link" else "Call for CV - Another call",
        body_text=(
            original.body_text.replace("SYNTHETIC-NOT-LIVE-P-D01", "different-explicit-link")
            if joining == "thread"
            else original.body_text
            if joining == "link"
            else "Reminder; details unchanged."
        ),
        sent_at=original.sent_at + timedelta(hours=1),
    )
    run(database, [original, newer])
    assert database.execute("SELECT count(*) FROM opportunities").fetchone()[0] == 1
    assert database.execute("SELECT count(*) FROM opportunity_revisions").fetchone()[0] == 2
    assert database.execute("SELECT count(*) FROM merge_suggestions").fetchone()[0] == 0


def test_linkless_revision_cannot_bridge_different_explicit_links(database):
    original = message("P-D01")
    reminder = replace(
        original,
        provider_id="linkless",
        thread_id="linkless-thread",
        sent_at=original.sent_at + timedelta(hours=1),
        body_text="Reminder.",
    )
    different = replace(
        original,
        provider_id="different",
        thread_id="different-thread",
        sent_at=original.sent_at + timedelta(hours=2),
        body_text=original.body_text.replace("SYNTHETIC-NOT-LIVE-P-D01", "another-link"),
    )
    run(database, [original, reminder, different])
    assert database.execute("SELECT count(*) FROM opportunities").fetchone()[0] == 2
    assert database.execute("SELECT reason FROM merge_suggestions").fetchone()[0] == (
        "same_subject_different_link"
    )


def test_full_import_opportunity_membership_matches_manifest_groups(database):
    # Group ids come from the authored case manifest, never from extraction output.
    cases = json.loads(Path("synth/cases.json").read_text(encoding="utf8"))["cases"]
    expected = {}
    for case in cases:
        if case["gold"]["category"] == "ps_call":
            expected.setdefault(case["group"], set()).add(case["id"])
    assert len([g for g in expected.values() if any(i.startswith("P-") for i in g)]) == 40
    assert len([g for g in expected.values() if any(i.startswith("J") for i in g)]) == 9
    assert all("J06" not in group for group in expected.values())
    counts = run(database, load(Path("fixtures/export_sample"), "synthetic"))
    actual = {}
    for row in database.execute(
        "SELECT r.opportunity_id,m.provider_id FROM opportunity_revisions r "
        "JOIN messages m ON m.id=r.message_id"
    ):
        actual.setdefault(row["opportunity_id"], set()).add(row["provider_id"])
    assert counts["opportunities"] == len(actual) == len(expected) == 49
    assert {frozenset(g) for g in actual.values()} == {frozenset(g) for g in expected.values()}
    group_ids = {
        identity: group_id for group_id, members in expected.items() for identity in members
    }
    actual_by_manifest_group = {}
    for members in actual.values():
        groups = {group_ids[identity] for identity in members}
        assert len(groups) == 1
        group_id = groups.pop()
        assert group_id not in actual_by_manifest_group
        actual_by_manifest_group[group_id] = members
    assert actual_by_manifest_group == expected
    assert extract_messages(database)["revisions"] == 0


def test_pause_entry_and_between_stages(database, monkeypatch):
    from inbound.extract import pipeline

    run(database, [])
    set_paused(database, True)
    with pytest.raises(PausedError):
        extract_messages(database)
    set_paused(database, False)
    import_messages(database, [message("P-D15")])
    triage_messages(database)
    real_parse = pipeline.parse_attachment

    def pause_after_attachment(a):
        result = real_parse(a)
        set_paused(database, True)
        return result

    monkeypatch.setattr(pipeline, "parse_attachment", pause_after_attachment)
    with pytest.raises(PausedError):
        extract_messages(database)
    assert database.execute("SELECT count(*) FROM opportunity_revisions").fetchone()[0] == 0
