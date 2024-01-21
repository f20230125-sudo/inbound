import json
from pathlib import Path

from eval.extract_baseline import baseline, metrics
from inbound.db import import_messages
from inbound.triage.rules import triage_messages
from tests.m2_helpers import message


def field(value, status="found"):
    return {"normalized": value, "status": status, "source_text": str(value), "raw": str(value)}


def test_hand_computed_denominators():
    gold = [
        {"mode": field("remote"), "deadline": field(None, "unknown")},
        {"mode": field("hybrid"), "deadline": field("2026-10-28")},
    ]
    actual = [
        {"mode": field("remote"), "deadline": field(None, "unknown")},
        {"mode": field(None, "unknown"), "deadline": field("2026-10-29")},
    ]
    report = metrics(gold, actual)
    assert report["applicable"] == {"correct": 2, "denominator": 4, "accuracy": 0.5}
    assert report["populated"]["correct"] == 1 and report["populated"]["denominator"] == 3
    assert report["full_record"]["correct"] == 1 and report["full_record"]["denominator"] == 2
    assert report["abstentions"] == 2
    assert report["silently_wrong_deadlines"] == 1


def test_bad_provenance_is_inaccurate_without_a_wrong_deadline_value():
    expected = {"deadline": field("2026-10-28")}
    actual = {"deadline": {**field("2026-10-28"), "_quote_valid": False}}
    report = metrics([expected], [actual])
    assert report["applicable"]["correct"] == 0
    assert report["silently_wrong_deadlines"] == 0


def test_unknown_requires_authored_missing_phrase_and_reason():
    expected = {
        "stipend": {
            **field(None, "unknown"),
            "raw": "As per company norms",
            "source_text": "As per company norms",
            "missing_reason": "No figure",
        }
    }
    actual = {"stipend": field(None, "unknown")}
    assert metrics([expected], [actual])["applicable"]["correct"] == 0


def test_dev_only(database, tmp_path):
    cases = json.loads(Path("synth/cases.json").read_text(encoding="utf8"))
    dev = [c for c in cases["cases"] if c["split"] == "dev"]
    import_messages(database, [message(c["id"]) for c in dev])
    triage_messages(database)
    report = baseline(database, tmp_path)
    assert report["denominator"] == 64 and report["held_out"] == "not scored"
    assert report["silently_wrong_deadlines"] == 0
    assert (tmp_path / "m2.json").is_file() and (tmp_path / "m2.md").is_file()
