"""Fictional unit cases for SPEC §14; independent of the frozen dataset."""

from datetime import UTC, datetime

import pytest

from inbound.extract.call import extract_call
from inbound.models import Message


def call(subject, body):
    return Message(
        provider_id="fictional-format",
        thread_id="fictional-thread",
        sent_at=datetime(2026, 10, 28, tzinfo=UTC),
        received_at=datetime(2026, 10, 28, tzinfo=UTC),
        sender="ps@dubai.bits-pilani.ac.in",
        source="synthetic",
        subject=subject,
        body_text=body,
    )


@pytest.mark.parametrize(
    "instruction",
    [
        "please apply directly through the link below",
        "Apply directly",
        "Careers page",
    ],
)
@pytest.mark.parametrize("wrapped", [False, True])
def test_bare_direct_apply_url_with_encoded_query(instruction, wrapped):
    first = (
        "https://recruit.harbor-finch.example/opening/842?cities=Port%2CSelene&role=Data+Science&"
    )
    second = "source=campus%2Coffice&team=Research+Engineering"
    raw = first + ("\n" if wrapped else "") + second
    m = call(
        "Call for CV - Harbor & Finch Advisory,Port Selene",
        f"Harbor & Finch Advisory has expressed their interest to hire students.\n"
        f"{instruction}\n{raw}\nPlease review the requirements before applying.",
    )
    result = extract_call(m)
    fields = result["fields"]
    assert result["kind"] == "direct_apply"
    assert fields["apply_link"]["status"] == "found"
    assert fields["apply_link"]["normalized"] == first + second
    assert fields["apply_link"]["source_text"] == raw
    assert fields["apply_link"]["provenance"]["message_id"] == m.provider_id
    assert fields["company"]["normalized"] == "Harbor & Finch Advisory"
    assert fields["city"]["normalized"] == "Port Selene"
    for name in ("form_link", "stipend", "deadline"):
        assert fields[name]["status"] == "unknown"
        assert fields[name]["normalized"] is None


@pytest.mark.parametrize(
    "prefix", ["Call for CV - ", "Fwd: Call for CV – PS II – Second Semester 2026-2027 – "]
)
def test_glued_company_role_without_city(prefix):
    m = call(
        prefix + "QX- Data Science Intern",
        "*QX*- *Data Science Intern*,has expressed their interest to hire students.",
    )
    fields = extract_call(m)["fields"]
    assert fields["company"]["status"] == "found"
    assert fields["company"]["normalized"] == "QX"
    assert fields["company"]["source_text"] == "QX"
    assert fields["city"]["status"] == "unknown"
    assert fields["city"]["normalized"] is None
    assert fields["roles"]["normalized"][0]["title"] == "Data Science Intern"
    assert fields["roles"]["provenance"]["source"] == "subject"


def test_company_em_dash_city_hyphen_role():
    m = call(
        "Call for CV – PS II – Second Semester 2026-2027 – "
        "Velora Systems Pvt Ltd — Riverton - Software Engineer Intern",
        "*Velora Systems Pvt Ltd — Riverton, *has expressed their interest to hire students.",
    )
    fields = extract_call(m)["fields"]
    for name, value in (("company", "Velora Systems Pvt Ltd"), ("city", "Riverton")):
        assert fields[name]["status"] == "found"
        assert fields[name]["normalized"] == value
        assert fields[name]["source_text"] in m.subject
    assert fields["roles"]["normalized"][0]["title"] == "Software Engineer Intern"


@pytest.mark.parametrize(
    "opening",
    [
        "*Harbor & Finch Advisory*,has expressed their interest to hire students.",
        "Harbor & Finch Advisory has expressed their interest to hire students.",
    ],
)
def test_body_confirms_company_for_ambiguous_subject(opening):
    m = call("Call for CV - Internship opportunities", opening)
    fields = extract_call(m)["fields"]
    assert fields["company"]["status"] == "found"
    assert fields["company"]["normalized"] == "Harbor & Finch Advisory"
    assert fields["company"]["source_text"] in m.body_text
    assert fields["city"]["status"] == "unknown"
    assert fields["roles"]["status"] == "unknown"


def test_disagreeing_body_company_keeps_both_observations():
    m = call(
        "Call for CV - Harbor & Finch Advisory,Port Selene - Data Intern",
        "*Velora Systems Pvt Ltd*, has expressed their interest to hire students.",
    )
    company = extract_call(m)["fields"]["company"]
    assert company["status"] == "conflicting"
    assert company["normalized"] is None
    assert {c["normalized"] for c in company["candidates"]} == {
        "Harbor & Finch Advisory",
        "Velora Systems Pvt Ltd",
    }
    assert {o["source"] for o in company["observations"]} == {"subject", "body"}
    for candidate in company["candidates"]:
        assert candidate["source_text"] in m.subject + "\n" + m.body_text
        assert candidate["provenance"]["message_id"] == m.provider_id


@pytest.mark.parametrize(
    "url",
    [
        "https://forms.gle/fictional-form",
        "https://docs.google.com/forms/d/e/fictional-form/viewform?entry=Port%2CSelene",
    ],
)
def test_direct_apply_wording_does_not_turn_forms_into_careers_urls(url):
    result = extract_call(call("Call for CV - QX,Port Selene", f"Apply directly\n{url}"))
    assert result["kind"] == "ps_call"
    assert result["fields"]["form_link"]["normalized"] == url
    assert result["fields"]["apply_link"]["status"] == "unknown"


def test_plain_unlabelled_url_is_not_enough_for_direct_apply():
    fields = extract_call(
        call("Call for CV - QX,Port Selene", "https://qx.example/about\nCompany background.")
    )["fields"]
    assert fields["apply_link"]["status"] == "unknown"


@pytest.mark.parametrize("following", ["Apply here: https://qx.example/apply/123", "Thanks"])
def test_url_wrapping_does_not_consume_following_prose(following):
    m = call(
        "Call for CV - QX,Port Selene",
        f"Company Website: https://qx.example/\n{following}",
    )
    website = extract_call(m)["fields"]["company_website"]
    assert website["normalized"] == "https://qx.example/"
    assert website["source_text"] == "https://qx.example/"


@pytest.mark.parametrize(
    "tail,opening,company,city,role",
    [
        (
            "Orchid Nine Labs,Port Selene",
            "*Orchid Nine Labs,Port Selene*,has expressed",
            "Orchid Nine Labs", "Port Selene", None,
        ),
        (
            "Orchid Nine Labs,\u200bPort Selene",
            "*Orchid Nine Labs,\u200bPort Selene*,has expressed",
            "Orchid Nine Labs", "Port Selene", None,
        ),
        (
            "Kestrel & Vane Ltd — Riverton - Data Intern",
            "*Kestrel & Vane Ltd — Riverton, *has expressed",
            "Kestrel & Vane Ltd", "Riverton", "Data Intern",
        ),
        (
            "QX- Data Science Intern",
            "*QX*- *Data Science Intern*,has expressed",
            "QX", None, "Data Science Intern",
        ),
        (
            "Brightwater Solutions/Al Noor, Harbor District,\u200bPort Selene",
            "*Brightwater Solutions/Al Noor, Harbor District,\u200bPort Selene*,has expressed",
            "Brightwater Solutions/Al Noor, Harbor District", "Port Selene", None,
        ),
        (
            "Orchid Nine Labs,Port Selene - Data Intern",
            "*Orchid Nine Labs,Port Selene - Data Intern*,has expressed",
            "Orchid Nine Labs", "Port Selene", "Data Intern",
        ),
        (
            "Kestrel & Vane Ltd — Riverton",
            "*Kestrel & Vane Ltd — Riverton*,has expressed",
            "Kestrel & Vane Ltd", "Riverton", None,
        ),
    ],
)
def test_body_repeated_company_city_role_keeps_agreeing_observations(
    tail, opening, company, city, role
):
    m = call(
        "Call for CV - PS II – Second Semester 2026-2027 – " + tail,
        opening + " their interest to hire Students for PS II.",
    )
    fields = extract_call(m)["fields"]
    for name, expected in (("company", company), ("city", city)):
        record = fields[name]
        if expected is None:
            assert record["status"] == "unknown"
            assert record["normalized"] is None
            continue
        assert record["status"] == "found"
        assert record["normalized"] == expected
        assert "candidates" not in record
        observations = record["observations"]
        assert [o["source"] for o in observations] == ["subject", "body"]
        assert [o["value"] for o in observations] == [expected, expected]
        for observation, source in zip(observations, (m.subject, m.body_text), strict=True):
            assert observation["source_text"] in source
            assert observation["message_id"] == m.provider_id
        if "\u200b" in tail:
            assert "\u200b" in fields["city"]["raw"]
            assert "\u200b" in observations[1]["source_text"]
    if role:
        assert fields["roles"]["normalized"][0]["title"] == role


def test_repeated_city_does_not_hide_a_genuine_company_disagreement():
    m = call(
        "Call for CV - Alpha Labs,Port Selene",
        "*Beta Labs,Port Selene*,has expressed their interest to hire Students.",
    )
    fields = extract_call(m)["fields"]
    company = fields["company"]
    assert company["status"] == "conflicting"
    assert company["normalized"] is None
    assert [c["normalized"] for c in company["candidates"]] == ["Alpha Labs", "Beta Labs"]
    assert [o["value"] for o in company["observations"]] == ["Alpha Labs", "Beta Labs"]
    for candidate, observation, source in zip(
        company["candidates"], company["observations"], (m.subject, m.body_text), strict=True
    ):
        assert candidate["source_text"] == observation["source_text"]
        assert candidate["source_text"] in source
        assert candidate["provenance"]["message_id"] == m.provider_id
    assert fields["city"]["status"] == "found"
    assert fields["city"]["normalized"] == "Port Selene"


@pytest.mark.parametrize("zero_width", ["\u200b", "\u200c", "\u200d", "\ufeff"])
@pytest.mark.parametrize("role_source", ["subject", "body"])
def test_normalized_company_city_roles_strip_zero_width_and_preserve_quotes(zero_width, role_source):
    company = f"Orchid{zero_width} Nine Labs"
    city = f"{zero_width}Port Selene"
    role = f"Data{zero_width} Intern"
    m = call(
        f"Call for CV - {company},{city} - {role}",
        f"*{company},{city}*,has expressed their interest to hire Students.\n"
        + (f"Job Title & JD\n*1. {role}*" if role_source == "body" else ""),
    )
    fields = extract_call(m)["fields"]
    for name, expected in (("company", "Orchid Nine Labs"), ("city", "Port Selene")):
        record = fields[name]
        assert record["status"] == "found"
        assert record["normalized"] == expected
        assert zero_width in record["raw"]
        assert zero_width in record["source_text"]
        assert record["source_text"] in m.subject
    roles = fields["roles"]
    assert roles["normalized"][0]["title"] == "Data Intern"
    assert zero_width in roles["raw"]
    assert zero_width in roles["source_text"]
    assert roles["source_text"] in (m.subject if role_source == "subject" else m.body_text)


@pytest.mark.parametrize(
    "subject,body,expected,status",
    [
        (
            "Call for CV - Alpha Labs,DSO",
            "*Alpha Labs,Dubai*,has expressed their interest to hire Students.",
            ["DSO", "Dubai"], "found",
        ),
        (
            "Call for CV - Alpha Labs,Port Selene",
            "*Alpha Labs,Riverton*,has expressed their interest to hire Students.",
            None, "conflicting",
        ),
    ],
)
def test_body_phrase_city_is_observed_separately_from_company(subject, body, expected, status):
    fields = extract_call(call(subject, body))["fields"]
    assert fields["company"]["status"] == "found"
    assert fields["company"]["normalized"] == "Alpha Labs"
    city = fields["city"]
    assert city["status"] == status
    assert city["normalized"] == expected
    assert [o["source"] for o in city["observations"]] == ["subject", "body"]


def test_labelled_city_normalization_preserves_its_source_quote():
    m = call("Call for CV - Alpha Labs,DSO", "City: \u200bDubai")
    city = extract_call(m)["fields"]["city"]
    assert city["status"] == "found"
    assert city["normalized"] == ["DSO", "Dubai"]
    assert city["observations"][1]["source_text"] == "\u200bDubai"
