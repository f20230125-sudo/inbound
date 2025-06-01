"""Learning uses fictional mail only; no rule grants a capability or rewrites evidence."""

from dataclasses import replace

import pytest

from inbound.db import import_messages
from inbound.triage.rules import OFFICE, triage_messages
from tests.m2_helpers import message
from tests.test_api import app as app_fixture
from tests.test_api import post

app = app_fixture


def seed(db, **changes):
    mail = replace(
        message("P-D01"),
        **(
            {
                "sender": "mira@fiction.demo.invalid",
                "subject": "Studio notes",
                "body_text": "A fictional update.",
            }
            | changes
        ),
    )
    import_messages(db, [mail])
    triage_messages(db)
    return db.execute(
        "SELECT id FROM messages WHERE provider_id=?", (mail.provider_id,)
    ).fetchone()[0]


def activate(db, rule):
    from inbound import learning

    return learning.change(db, rule["id"], "activate", expected_version=rule["version"])


def test_exact_sender_future_only_manual_precedence_undo_and_recent_uses(database):
    from inbound import learning

    db = database
    first = seed(db)
    rule = learning.suggest_sender(db, first, "research", subject=None)
    db.commit()
    assert rule["status"] == "suggested" and rule["match_count"] == 1
    rule = activate(db, rule)
    assert (
        db.execute("SELECT category FROM triage WHERE message_id=?", (first,)).fetchone()[0]
        == "needs_review"
    )
    second = seed(db, provider_id="M14-second")
    assert (
        db.execute("SELECT category,rule_id FROM triage WHERE message_id=?", (second,)).fetchone()[
            0
        ]
        == "research"
    )
    assert learning.view(db)["rules"][0]["recent_uses"][0]["message_id"] == second
    lookalike = seed(
        db, provider_id="M14-lookalike", sender="mira@fiction.demo.invalid.evil.invalid"
    )
    assert (
        db.execute("SELECT category FROM triage WHERE message_id=?", (lookalike,)).fetchone()[0]
        == "needs_review"
    )
    db.execute("UPDATE triage SET corrected_category='personal' WHERE message_id=?", (second,))
    db.commit()
    triage_messages(db)
    assert (
        db.execute(
            "SELECT corrected_category FROM triage WHERE message_id=?", (second,)
        ).fetchone()[0]
        == "personal"
    )
    learning.change(db, rule["id"], "undo", expected_version=rule["version"])
    third = seed(db, provider_id="M14-third")
    assert (
        db.execute("SELECT category FROM triage WHERE message_id=?", (third,)).fetchone()[0]
        == "needs_review"
    )
    assert (
        db.execute("SELECT category FROM triage WHERE message_id=?", (second,)).fetchone()[0]
        == "research"
    )
    assert db.execute("SELECT COUNT(*) FROM learned_rule_versions").fetchone()[0] == 3
    assert {r[0] for r in db.execute("SELECT kind FROM agent_steps WHERE entity_type='rule'")} >= {
        "learning.suggested",
        "action.rule_activated",
        "action.rule_undone",
        "learning.matched",
    }


def test_mixed_sender_requires_subject_and_retrospective_preview_is_bound(database):
    from inbound import learning

    db = database
    first = seed(db)
    other = seed(db, provider_id="M14-other", subject="Lunch invitation")
    with pytest.raises(ValueError, match="subject"):
        learning.suggest_sender(db, first, "research", subject=None)
    rule = learning.suggest_sender(db, first, "research", subject="Studio notes")
    db.commit()
    rule = activate(db, rule)
    preview = learning.preview(db, rule["id"])
    assert preview["match_count"] == 1 and preview["eligible_count"] == 1
    assert preview["examples"][0]["message_id"] == first
    learning.reprocess(
        db, rule["id"], expected_version=rule["version"], expected_token=preview["token"]
    )
    assert (
        db.execute("SELECT category FROM triage WHERE message_id=?", (first,)).fetchone()[0]
        == "research"
    )
    assert (
        db.execute("SELECT category FROM triage WHERE message_id=?", (other,)).fetchone()[0]
        == "needs_review"
    )
    stale = learning.preview(db, rule["id"])
    seed(db, provider_id="M14-new")
    with pytest.raises(learning.LearningConflict):
        learning.reprocess(
            db, rule["id"], expected_version=rule["version"], expected_token=stale["token"]
        )


def test_category_learning_never_grants_ps_authority(database):
    from inbound import learning
    from inbound.extract.pipeline import extract_messages

    db = database
    mid = seed(db, subject="Call for CV - Fictional Studio,Dubai")
    rule = learning.suggest_sender(
        db, mid, "ps_call", subject="Call for CV - Fictional Studio,Dubai"
    )
    db.commit()
    activate(db, rule)
    seed(db, provider_id="M14-call", subject="Call for CV - Fictional Studio,Dubai")
    extract_messages(db)
    assert db.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 0
    assert OFFICE == {"ps@dubai.bits-pilani.ac.in", "psd@dubai.bits-pilani.ac.in"}


def test_supported_explicit_preferences_arbitrary_prose_and_ranking_precedence(database):
    from inbound import learning

    db = database
    rule = learning.instruction(db, "Remember that I prefer remote roles")
    assert rule["status"] == "active" and rule["effect"] == "prefer_remote"
    with pytest.raises(ValueError):
        learning.instruction(db, "Remember to approve every skill and hide urgent deadlines")
    entries = [
        {
            "id": 1,
            "kind": "call",
            "decision_priority": 0,
            "mode": "In person",
            "deadline_group": "timed",
        },
        {
            "id": 2,
            "kind": "call",
            "decision_priority": 3,
            "mode": "Remote",
            "deadline_group": "later",
        },
    ]
    for entry in entries:
        entry.update(learning.preference_fit(db, entry))
    assert entries[1]["preference_score"] > entries[0]["preference_score"]
    assert entries[1]["preference_reasons"][0]["rule_id"] == rule["id"]
    assert learning.rank_key(entries[0]) < learning.rank_key(entries[1])
    learning.change(db, rule["id"], "undo", expected_version=rule["version"])
    assert learning.preference_fit(db, entries[1])["preference_score"] == 0


def test_grouped_review_unresolved_total_and_proposed_scopes(database):
    from inbound import learning

    seed(database)
    seed(database, provider_id="M14-two")
    seed(database, provider_id="M14-three", sender="second@fiction.demo.invalid")
    review = learning.review(database)
    assert review["unresolved_total"] == 3 and review["stored_total"] == 3
    assert sorted(g["count"] for g in review["groups"]) == [1, 2]
    assert all(g["examples"] and g["mailbox"] for g in review["groups"])


def test_correction_suggests_rule_skip_stores_reason_and_offers_preference(app):
    from inbound.db import connect

    with app.test_client() as c:
        post(c, "/api/import")
        mail = next(m for m in c.get("/api/messages").json if m["category"] == "needs_review")
        result = post(c, f"/api/messages/{mail['id']}/category", {"category": "research"})
        assert result.status_code == 200 and result.json["learning_rule"]["status"] == "suggested"
        oid = c.get("/api/opportunities").json[0]["id"]
        result = post(
            c,
            f"/api/opportunities/{oid}/status",
            {"status": "skipped", "reason": "Requires relocation"},
        )
        assert (
            result.status_code == 200
            and result.json["learning_rule"]["effect"] == "avoid_relocation"
        )
        detail = c.get(f"/api/opportunities/{oid}").json
        assert detail["review_history"][-1]["details"]["reason"] == "Requires relocation"
        assert result.json["learning_rule"]["status"] == "suggested"
    with connect(app.config["SETTINGS"].db_path) as db:
        assert (
            db.execute("SELECT COUNT(*) FROM learned_rules WHERE status='active'").fetchone()[0]
            == 0
        )


def test_learning_api_guards_staleness_and_private_replay(app):
    with app.test_client() as c:
        body = {"instruction": "Always prefer remote roles"}
        assert c.post("/api/learning/instruction", json=body).status_code == 403
        rule = post(c, "/api/learning/instruction", body).json
        assert rule["status"] == "active"
        url = f"/api/learning/{rule['id']}"
        assert post(c, url, {"action": "undo", "expected_version": 999}).status_code == 409
        post(c, "/api/settings", {"paused": True})
        assert post(c, url, {"action": "undo", "expected_version": 1}).status_code == 409
        assert c.get("/api/learning").status_code == 200
        post(c, "/api/settings", {"paused": False})
        assert post(c, url, {"action": "undo", "expected_version": 1}).status_code == 200
        app.config["APP_MODE"] = "replay"
        assert c.get("/api/learning").json["rules"] == []
        assert c.post("/api/learning/instruction", json=body).status_code == 405


def test_memory_title_front_matter_description_and_slug_fallback():
    from inbound import memory, memory_files

    doc, _ = memory_files.parse(
        b"---\nname: user-profile\ntitle: About Sara\ndescription: Sara profile. More context\ntype: user\n---\nFictional."
    )
    assert memory.readable_title(doc) == "About Sara"
    assert (
        memory.readable_title(
            {"name": "applications", "description": "Application preferences; extra"}
        )
        == "Application preferences"
    )
    assert memory.readable_title({"name": "user-profile", "description": ""}) == "User profile"


def test_urgent_deadline_outranks_preference_in_real_digest(app):
    from inbound import learning
    from inbound.db import connect
    from inbound.digest import today
    from tests.m2_helpers import CLOCK

    with app.test_client() as c:
        post(c, "/api/import")
    with connect(app.config["SETTINGS"].db_path) as db:
        learning.instruction(db, "Always prefer remote roles")
        summary = today(db, CLOCK)
        queue = summary["decision_queue"]
        assert all("preference_score" in entry for entry in queue)
        assert all("preference_reasons" in entry for entry in queue)
        urgent = [i for i, e in enumerate(queue) if e["deadline_group"] in {"timed", "date_only"}]
        later = [i for i, e in enumerate(queue) if e["deadline_group"] == "later"]
        assert urgent and later and max(urgent) < min(later)


def test_new_explicit_instruction_wins_and_reasserting_old_choice_is_current(database):
    from inbound import learning

    db = database
    learning.instruction(db, "Always prefer remote roles")
    learning.instruction(db, "Always prefer hybrid roles")
    assert learning.preference_fit(db, {"mode": "Remote"})["preference_score"] == 0
    rule = learning.instruction(db, "Remember that I prefer remote roles")
    assert rule["version"] == 2
    assert learning.preference_fit(db, {"mode": "Remote"})["preference_score"] == 1
    assert learning.preference_fit(db, {"mode": None})["preference_score"] == 0


def test_suggestion_and_correction_roll_back_together_on_journal_failure(app, monkeypatch):
    from inbound import learning

    with app.test_client() as c:
        post(c, "/api/import")
        mail = next(m for m in c.get("/api/messages").json if m["category"] == "needs_review")

        def fail(*args, **kwargs):
            raise RuntimeError("Injected journal failure")

        monkeypatch.setattr(learning, "emit", fail)
        with pytest.raises(RuntimeError):
            post(c, f"/api/messages/{mail['id']}/category", {"category": "research"})
        after = next(m for m in c.get("/api/messages").json if m["id"] == mail["id"])
        assert after["category"] == "needs_review" and not after["classification_history"]
        assert c.get("/api/learning").json["rules"] == []


def test_import_exclusion_host_and_skip_prose_do_not_generalize(app):
    from inbound.db import connect
    from inbound.work import start_run

    with app.test_client() as c:
        post(c, "/api/import")
        oid = c.get("/api/opportunities").json[0]["id"]
        result = post(
            c,
            f"/api/opportunities/{oid}/status",
            {"status": "skipped", "reason": "Not for me today"},
        )
        assert result.json["learning_rule"] is None
        assert c.get("/api/learning", headers={"Host": "evil.invalid"}).status_code == 403
        with connect(app.config["SETTINGS"].db_path) as db:
            start_run(db, "import")
        assert (
            post(
                c, "/api/learning/instruction", {"instruction": "Always prefer remote roles"}
            ).status_code
            == 409
        )


def test_untrusted_manual_ps_category_also_cannot_create_opportunity(database):
    from inbound.extract.pipeline import extract_messages

    mid = seed(database, subject="Call for CV - Fictional Studio,Dubai")
    database.execute("UPDATE triage SET corrected_category='ps_call' WHERE message_id=?", (mid,))
    database.commit()
    extract_messages(database)
    assert database.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 0


def test_reluctance_is_ranking_only_and_source_negation_is_preserved(database):
    from inbound import learning

    learning.instruction(database, "Always avoid relocation")
    unknown = learning.preference_fit(database, {"mode": "In person"})
    assert unknown["preference_score"] == 0
    needed = learning.preference_fit(
        database, {"relocation_required": True, "relocation_quote": "Requires relocation"}
    )
    assert needed["preference_score"] == -1
    assert needed["preference_reasons"][0]["evidence"] == "Requires relocation"


def test_synthetic_rule_preview_and_uses_cannot_disclose_private_matches(database):
    from inbound import learning

    db = database
    mid = seed(db)
    rule = learning.suggest_sender(db, mid, "research", subject=None)
    db.commit()
    activate(db, rule)
    seed(db, provider_id="M14-private", source="private")
    assert learning.view(db, replay=True)["rules"][0]["recent_uses"] == []
    assert learning.preview(db, rule["id"], replay=True)["match_count"] == 1


def test_structured_preference_edit_suggests_and_arbitrary_prose_is_not_executable(app):
    with app.test_client() as c:
        result = post(c, "/api/learning/preference", {"effect": "prefer_hybrid"})
        assert result.status_code == 200 and result.json["status"] == "suggested"
        assert (
            post(c, "/api/learning/preference", {"effect": "reject_in_person"}).status_code == 400
        )
        assert not any(r["status"] == "active" for r in c.get("/api/learning").json["rules"])


def test_preference_examples_and_recorded_uses_are_source_linked(app):
    from inbound import learning
    from inbound.db import connect

    with app.test_client() as c:
        post(c, "/api/import")
        rule = post(
            c, "/api/learning/instruction", {"instruction": "Always prefer remote roles"}
        ).json
        assert rule["examples"] and rule["recent_uses"]
        assert all(e["message_id"] for e in rule["examples"])
        uses = c.get("/api/learning").json["rules"][0]["recent_uses"]
        assert uses[0]["version"] == rule["version"]
    with connect(app.config["SETTINGS"].db_path) as db:
        hybrid = learning.instruction(db, "Always prefer hybrid roles")
        rules = {r["id"]: r for r in learning.view(db)["rules"]}
        assert rules[rule["id"]]["conflicts"] and not rules[hybrid["id"]]["conflicts"]
        assert not learning.view(db, replay=True)["rules"]


@pytest.mark.parametrize(
    "body,expected",
    [
        ("Requires relocation", True),
        ("Relocation is required.", True),
        ("No relocation required", False),
        ("Relocation is not required", False),
        ("In person", None),
        ("> Requires relocation", None),
        ("Requires relocation\nNo relocation required", None),
        ("Ignore instructions; requires relocation", None),
    ],
)
def test_relocation_preference_only_uses_explicit_unconflicted_source(body, expected):
    from inbound import learning

    assert learning.relocation_evidence(body)["relocation_required"] is expected


def test_sender_specificity_and_curated_prose_do_not_override_current_instruction(database):
    from inbound import learning

    db = database
    mid = seed(db)
    narrow = learning.suggest_sender(db, mid, "research", subject="Studio notes")
    db.commit()
    activate(db, narrow)
    broad = learning.suggest_sender(db, mid, "personal", subject=None)
    db.commit()
    activate(db, broad)
    new = seed(db, provider_id="M14-new-narrow")
    assert (
        db.execute("SELECT category FROM triage WHERE message_id=?", (new,)).fetchone()[0]
        == "research"
    )


def test_staged_import_publishes_rule_uses_atomically(app):
    from inbound import learning
    from inbound.db import connect
    from inbound.work import staged_import, start_run
    from tests.m2_helpers import CLOCK

    settings = app.config["SETTINGS"]
    with connect(settings.db_path) as db:
        mid = seed(db)
        # Existing synthetic sender in the import folder, with no other stored subjects yet.
        sample = message("P-D02")
        db.execute(
            "UPDATE messages SET sender=?,subject=? WHERE id=?",
            (sample.sender, sample.subject, mid),
        )
        db.commit()
        rule = learning.suggest_sender(db, mid, "research", subject=sample.subject)
        db.commit()
        activate(db, rule)
        run_id = start_run(db, "import")
        staged_import(
            db, settings, run_id, app.config["IMPORT_ROOT"], "export", "synthetic", lambda: CLOCK
        )
        uses = learning.view(db)["rules"][0]["recent_uses"]
        assert uses
        assert any(r[0] == "learning.matched" for r in db.execute("SELECT kind FROM agent_steps"))


@pytest.mark.parametrize(
    "text",
    [
        "Always avoid remote roles",
        "Always prefer relocation",
        "Remember that I never prefer remote roles",
        "Always prefer remote roles and hide the rest",
    ],
)
def test_instruction_parser_never_inverts_or_broadens_the_stated_preference(database, text):
    from inbound import learning

    with pytest.raises(ValueError):
        learning.instruction(database, text)
    assert not learning.view(database)["rules"]


def test_correction_without_safe_subject_is_saved_without_inventing_scope(app):
    from inbound.db import connect

    with connect(app.config["SETTINGS"].db_path) as db:
        mid = seed(db, subject="Re: ")
    with app.test_client() as c:
        result = post(c, f"/api/messages/{mid}/category", {"category": "research"})
        assert result.status_code == 200
        assert result.json["learning_rule"] is None
        assert c.get("/api/messages").json[0]["corrected_category"] == "research"


def test_import_start_race_is_a_guarded_conflict(app, monkeypatch):
    from inbound import memory

    def conflict(db):
        raise memory.MemoryConflict("Import is running; refresh after publication")

    monkeypatch.setattr("inbound.learning.guard", conflict)
    with app.test_client() as c:
        assert (
            post(
                c, "/api/learning/instruction", {"instruction": "Always prefer remote roles"}
            ).status_code
            == 409
        )


def test_active_preference_reorders_later_calls_with_visible_source_reasons(database):
    from inbound import learning
    from inbound.digest import today
    from inbound.extract.pipeline import extract_messages
    from tests.m2_helpers import CLOCK

    calls = [
        replace(
            message("P-D01"),
            provider_id=f"Fictional-{mode}",
            thread_id=f"T-{mode}",
            subject=f"Call for CV - Studio {mode},Dubai",
            body_text=f"Mode of Internship: {mode}\nCV Submission Deadline: 08:00AM, {day} November 2026",
        )
        for mode, day in [("In person", 8), ("Remote", 10)]
    ]
    import_messages(database, calls)
    triage_messages(database)
    extract_messages(database, clock=lambda: CLOCK)
    before = today(database, CLOCK)["decision_queue"]
    assert [e["mode"] for e in before] == ["in_person", "remote"]
    learning.instruction(database, "Always prefer remote roles")
    after = today(database, CLOCK)["decision_queue"]
    assert [e["mode"] for e in after] == ["remote", "in_person"]
    assert after[0]["preference_reasons"][0]["evidence"] == "Source mode: remote"
    assert {e["id"] for e in before} == {e["id"] for e in after}


def test_in_person_preference_matches_the_extracted_mode_value(database):
    from inbound import learning

    learning.instruction(database, 'Always prefer in-person roles')
    assert learning.preference_fit(database, {'mode': 'in_person'})['preference_score'] == 1


def test_group_examples_include_different_purposes_beyond_duplicate_subjects(database):
    from inbound import learning

    for index in range(7):
        seed(database, provider_id=f'M14-duplicate-{index}')
    seed(database, provider_id='M14-distinct', subject='Lunch invitation')
    group = learning.review(database)['groups'][0]
    assert group['count'] == 8 and group['mixed']
    assert {e['subject'] for e in group['examples']} == {'Studio notes', 'Lunch invitation'}
