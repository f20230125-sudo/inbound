"""Post-blind regressions: new fictional examples, independent of frozen case ids/gold."""

from dataclasses import replace

import pytest

from inbound.extract.call import extract_call
from tests.test_real_format_variants import call


@pytest.mark.parametrize(
    "label,date_text,time,expected,status",
    [
        ("Final extension", "tomorrow", "11:45 AM", "2026-10-29T11:45:00+04:00", "inferred"),
        ("Deadline", "today", "2 PM", "2026-10-28T14:00:00+04:00", "inferred"),
        ("Closing time", "3 November 2026", "1645 hrs", "2026-11-03T16:45:00+04:00", "found"),
        ("Deadline", "3 November 2026", "14:20 UTC", "2026-11-03T18:20:00+04:00", "found"),
    ],
)
def test_wrapped_deadline_keeps_time_and_original_quote(label, date_text, time, expected, status):
    raw = f"{label}: {date_text} at \n{time}"
    m = call(
        "Call for CV - Copper Heron Labs,Port Selene",
        raw + "\n\n--- Original message ---\n> Deadline: tomorrow at 7 AM",
    )
    result = extract_call(m)
    deadline = result["fields"]["deadline"]
    assert deadline["normalized"] == expected
    assert deadline["status"] == status
    assert deadline["precision"] == "minute"
    assert deadline["raw"] == deadline["source_text"] == raw
    assert deadline["source_text"] in m.body_text
    assert deadline["provenance"]["message_id"] == m.provider_id
    if status == "inferred":
        assert deadline["anchor"] == m.sent_at.isoformat()
    assert result["amendment"] == (label == "Final extension")


def test_wrapped_admin_deadline_keeps_time():
    m = replace(
        call("PS student records", "Please respond on or before tomorrow at \n09:15 AM"),
        subject="Student records survey",
    )
    deadline = extract_call(m, category="ps_admin")["fields"]["admin_deadline"]
    assert deadline["normalized"] == "2026-10-29T09:15:00+04:00"
    assert deadline["source_text"] == "on or before tomorrow at \n09:15 AM"


def test_date_only_deadline_does_not_borrow_time_from_another_fact():
    deadline = extract_call(
        call(
            "Call for CV - Copper Heron Labs,Port Selene",
            "Deadline: 3 November 2026\nOffice opens at 09:15 AM",
        )
    )["fields"]["deadline"]
    assert deadline["normalized"] == "2026-11-03"
    assert deadline["precision"] == "date"


@pytest.mark.parametrize("separator", [", ", "; "])
def test_inline_numbered_positions_keep_titles_requirements_and_source(separator):
    m = call(
        "Call for CV - Copper Heron Labs,Port Selene",
        "Job Title & JD\nPositions available: "
        "1. Data Platform Trainee. Expected Skills: "
        + separator.join(["PostgreSQL", "dbt", "data modelling"])
        + ". 2. Quality Analyst. Expected Skills: "
        + separator.join(["Playwright", "test planning"])
        + ".\nMode of Internship: Hybrid\nDeadline: 3 November 2026 at 4 PM",
    )
    fields = extract_call(m)["fields"]
    roles_field = fields["roles"]
    roles = roles_field["normalized"]
    assert roles_field["status"] == "found"
    assert [r["title"] for r in roles] == ["Data Platform Trainee", "Quality Analyst"]
    assert [[q["text"] for q in r["requirements"]] for r in roles] == [
        ["PostgreSQL", "dbt", "data modelling"],
        ["Playwright", "test planning"],
    ]
    assert fields["role_count"]["normalized"] == 2
    assert roles_field["source_text"] in m.body_text
    assert roles_field["provenance"]["source"] == "message"
    assert roles_field["provenance"]["message_id"] == m.provider_id
    for i, role in enumerate(roles, 1):
        assert role["id"] == f"{m.provider_id}-r{i}"
        assert [q["id"] for q in role["requirements"]] == [
            f"{role['id']}-q{j}" for j in range(1, len(role["requirements"]) + 1)
        ]


@pytest.mark.parametrize("layout", ["sentences", "bullets"])
def test_positions_label_without_separate_jd_heading(layout):
    text = (
        "Positions available: 1. Data Platform Trainee. Expected Skills: PostgreSQL, dbt. "
        "2. Quality Analyst. Requirements: Playwright."
        if layout == "sentences"
        else "Positions available: 1. Data Platform Trainee\nExpected Skills:\n"
        "- PostgreSQL\n- dbt\n2. Quality Analyst\nRequirements:\n- Playwright"
    )
    fields = extract_call(call("Call for CV - Copper Heron Labs,Port Selene", text))["fields"]
    assert fields["jd_location"]["normalized"] == "inline"
    roles = fields["roles"]["normalized"]
    assert [r["title"] for r in roles] == ["Data Platform Trainee", "Quality Analyst"]
    assert [[q["text"] for q in r["requirements"]] for r in roles] == [
        ["PostgreSQL", "dbt"], ["Playwright"],
    ]
    assert fields["roles"]["source_text"] in text
