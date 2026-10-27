import pytest

from inbound.extract.attachments import parse_attachment
from inbound.extract.call import extract_call
from inbound.triage.rules import classify
from tests.m2_helpers import message


@pytest.mark.parametrize("identity", [f"J{i:02}" for i in range(1, 11)])
def test_attacks(identity):
    m = message(identity)
    result = extract_call(m, [parse_attachment(a) for a in m.attachments])
    assert result["attack_suspected"] and result["attack_quotes"]
    if identity == "J06":
        assert classify(m.sender, m.subject, m.body_text).category != "ps_call"
        assert not result["creates_opportunity"]
    elif identity in {"J09", "J10"}:
        deadline = result["fields"]["deadline"]
        assert deadline["status"] == "conflicting" and deadline["normalized"] is None
        assert len(deadline["candidates"]) == 2
        later = "29" if identity == "J09" else "30"
        assert {c["normalized"] for c in deadline["candidates"]} == {
            "2026-10-28T08:00:00+04:00",
            f"2026-10-{later}T08:00:00+04:00",
        }
        assert all(
            c["source_text"] and c["provenance"]["message_id"] == identity
            for c in deadline["candidates"]
        )
        if identity == "J09":
            assert {c["provenance"]["source"] for c in deadline["candidates"]} == {
                "message",
                "attachment",
            }
    else:
        assert result["fields"]["deadline"]["normalized"] == "2026-10-28T08:00:00+04:00"
        assert result["fields"]["mode"]["normalized"] == "in_person"
        roles = result["fields"]["roles"]["normalized"]
        assert [q["text"] for q in roles[0]["requirements"]] == ["Python", "Flask", "SQL"]


@pytest.mark.parametrize("identity", [f"J{i:02}" for i in range(1, 11)])
def test_persisted_attack_outcomes_and_counts_only_ledger(database, monkeypatch, capsys, identity):
    import json
    from types import SimpleNamespace

    from inbound.__main__ import main
    from inbound.db import import_messages
    from inbound.settings import Settings
    from inbound.triage.rules import triage_messages

    path = database.execute("PRAGMA database_list").fetchone()["file"]
    monkeypatch.setattr(Settings, "from_env", lambda: SimpleNamespace(db_path=path))
    # Frozen attack groups are independent experiments. Their identical subjects would
    # otherwise join under SPEC §13; subject collisions are tested in test_revisions.
    import_messages(database, [message(identity)])
    triage_messages(database)
    assert main(["extract"]) == 0
    output = json.loads(capsys.readouterr().out)
    expected_opportunities = 0 if identity == "J06" else 1
    assert output["opportunities"] == expected_opportunities and output["attacks"] == 1
    assert all(isinstance(value, int) for value in output.values())
    assert (
        database.execute(
            "SELECT count(*) FROM opportunities WHERE status='submitted_by_me'"
        ).fetchone()[0]
        == 0
    )
    assert (
        database.execute("SELECT count(*) FROM triage WHERE category='ps_call'").fetchone()[0]
        == expected_opportunities
    )
    run = database.execute("SELECT * FROM runs ORDER BY id DESC").fetchone()
    assert json.loads(run["counts_json"]) == output
    assert run["model_calls"] == run["cache_hits"] == 0 and run["status"] == "success"
    assert "SYNTHETIC-CANARY" not in str(dict(run))
