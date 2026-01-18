from dataclasses import replace

import pytest

from inbound.extract.call import extract_call
from tests.m2_helpers import message


@pytest.mark.parametrize(
    "identity",
    [
        "P-D01",
        "P-D02",
        "P-D03",
        "P-D04",
        "P-D05",
        "P-D06",
        "P-D10",
        "P-D11",
        "P-D12",
        "P-D13",
        "P-D14",
        "P-D19",
    ],
)
def test_call_variants(identity):
    m = message(identity)
    fields = extract_call(m)["fields"]
    assert fields["company"]["status"] == fields["city"]["status"] == "found"
    assert fields["roles"]["status"] == "found"
    assert all(
        {"name", "raw", "normalized", "status", "source_text"} <= f.keys() for f in fields.values()
    )


def test_observed_cities_and_zero_width():
    city = extract_call(message("P-D04"))["fields"]["city"]
    assert city["normalized"] == ["DSO", "Dubai"] and city["status"] == "found"
    assert [o["source"] for o in city["observations"]] == ["subject", "body"]
    assert extract_call(message("P-D03"))["fields"]["company"]["normalized"] == "Nacre Relay"


def test_direct_absent_naming_and_dates():
    direct = extract_call(message("P-D11"))
    assert direct["kind"] == "direct_apply"
    assert (
        direct["fields"]["apply_link"]["normalized"]
        != (direct["fields"]["company_website"]["normalized"])
    )
    assert direct["fields"]["deadline"]["normalized"] is None
    absent = extract_call(message("P-D05"))["fields"]
    assert absent["jd_location"]["normalized"] == "absent"
    assert absent["cv_naming_rule"]["normalized"] == "DEMO-2023-CS-0042_Sara-Qamar_<Company>.pdf"
    dates = extract_call(message("P-D19"))["fields"]["internship_dates"]
    assert dates["normalized"] == {"start": "2027-01-04", "end": "2027-07-09"}


def test_incomplete_and_quoted_relative_not_reanchored():
    m = message("P-D01")
    incomplete = extract_call(replace(m, body_text="", body_complete=False))["fields"]
    assert incomplete["jd_location"]["status"] == "unknown"
    reminder = message("P-D07")
    current = reminder.body_text.split("--- Original message ---")[0]
    quoted = current + "\n--- Original message ---\n> Deadline: 08:00AM tomorrow"
    fields = extract_call(replace(reminder, body_text=quoted))["fields"]
    assert fields["deadline"]["normalized"] == "2026-10-28T08:00:00+04:00"
    assert fields["form_link"]["status"] == "unknown"


@pytest.mark.parametrize("identity,disposition", [("P-D23", "under_review"), ("P-D24", "sent")])
def test_application_update_facts(identity, disposition):
    result = extract_call(message(identity))
    assert not result["creates_opportunity"]
    assert result["fields"]["disposition"]["normalized"] == disposition
    assert result["fields"]["application_reference"]["normalized"] == (
        "d12" if identity == "P-D23" else None
    )


def test_literal_comma_company_and_unsafe_url():
    m = replace(
        message("P-D01"),
        subject="Call for CV - Maple, Fictional Labs,City - QA Intern",
        body_text="Company Website: javascript:alert(1)\nLocation: City",
    )
    fields = extract_call(m)["fields"]
    assert fields["company"]["normalized"] == "Maple, Fictional Labs"
    assert fields["company"]["source_text"] == "Maple, Fictional Labs"
    assert fields["company_website"]["status"] == "unknown"


def test_nonintern_role_and_competing_city():
    m = replace(
        message("P-D01"),
        subject="Call for CV - Fictional Company,Northville - Data Analyst",
        body_text="Location: Southville",
    )
    fields = extract_call(m)["fields"]
    assert fields["company"]["normalized"] == "Fictional Company"
    assert fields["roles"]["normalized"][0]["title"] == "Data Analyst"
    assert fields["city"]["status"] == "conflicting"
    assert {c["normalized"] for c in fields["city"]["candidates"]} == {"Northville", "Southville"}


def test_admin_date_only_conflict_stays_message_bound():
    m = replace(
        message("P-D21"),
        body_text="Please respond on or before 28 October 2026\nRespond by 29 October 2026",
    )
    result = extract_call(m)
    assert not result["creates_opportunity"]
    deadline = result["fields"]["admin_deadline"]
    assert deadline["status"] == "conflicting" and deadline["normalized"] is None
    assert {c["normalized"] for c in deadline["candidates"]} == {"2026-10-28", "2026-10-29"}
    assert all(c["provenance"]["message_id"] == m.provider_id for c in deadline["candidates"])
