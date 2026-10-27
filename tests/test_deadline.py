from datetime import datetime

import pytest

from inbound.extract.deadline import expired, parse_deadline
from inbound.triage.rules import urgency

SENT = datetime.fromisoformat("2026-10-27T23:50:00+04:00")


@pytest.mark.parametrize(
    "raw",
    [
        "**: 08**:00AM , 28 October 2026*",
        "8:00 AM, 28 October 2026",
        "0800 hrs, 28 October 2026",
        "28 October 2026 at 8 AM",
        "28 October 2026, 08:00",
        "28 Oct 2026 at 08:00 AM",
    ],
)
def test_formats(raw):
    field = parse_deadline(raw, SENT, SENT)
    assert field["normalized"] == "2026-10-28T08:00:00+04:00"
    assert field["status"] == "found"
    assert field["raw"] == field["source_text"] == raw


@pytest.mark.parametrize("phrase,date", [("tomorrow", "2026-10-28"), ("today", "2026-10-27")])
def test_relative_sent_time(phrase, date):
    received = datetime.fromisoformat("2026-10-29T01:00:00+04:00")
    field = parse_deadline("on or before 08:00AM " + phrase, SENT, received)
    assert field["normalized"] == date + "T08:00:00+04:00"
    assert field["status"] == "inferred"
    assert field["anchor"] == SENT.isoformat()
    assert phrase in field["raw"]
    assert field["past_at_receipt"]


def test_date_only_unknown_and_expiry():
    field = parse_deadline("on or before 29 October 2026", SENT, SENT)
    assert field["normalized"] == "2026-10-29"
    assert field["precision"] == "date"
    assert expired(field, SENT) is False
    assert expired(parse_deadline("", SENT, SENT), SENT) is None
    assert urgency("2026-10-29", SENT) == "high"
    assert urgency("2026-11-02", SENT) == "normal"
    assert urgency(SENT.isoformat(), SENT) == "normal"


def test_past_and_utc_and_dst_free():
    assert parse_deadline("26 October 2026, 19:00 UTC", SENT, SENT)["normalized"] == (
        "2026-10-26T23:00:00+04:00"
    )
    assert parse_deadline("08:00AM, 26 October 2026", SENT, SENT)["past_at_receipt"]
    for month in ("January", "July"):
        assert parse_deadline(f"28 {month} 2026, 08:00AM", SENT, SENT)["normalized"].endswith(
            "+04:00"
        )


@pytest.mark.parametrize("raw", ["31 February 2026, 08:00AM", "28 October 2026, 29:00"])
def test_invalid_abstains(raw):
    assert parse_deadline(raw, SENT, SENT)["status"] == "unknown"
