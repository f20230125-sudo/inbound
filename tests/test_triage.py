from datetime import datetime
from pathlib import Path

import pytest

from inbound.sources.export_txt import load
from inbound.triage.normalize import normalize_subject
from inbound.triage.rules import classify, urgency
from inbound.triage.taxonomy import CATEGORIES


@pytest.mark.parametrize(
    "subject",
    ["Fwd: Re: Call for CV — X", "\ufeffCall for C\u200dV – X", " Re:   Fwd: Call for CV - X"],
)
def test_normalize(subject):
    assert normalize_subject(subject) == "Call for CV - X"


@pytest.mark.parametrize(
    "sender,subject,body,expected",
    [
        ("ps@dubai.bits-pilani.ac.in", "Call for CV", "", "ps_call"),
        ("ps@dubai-bits-pilani.ac.in", "Call for CV", "", "needs_review"),
        ("ps@evil.invalid", "Survey", "", "needs_review"),
        ("ps@dubai.bits-pilani.ac.in.evil.invalid", "Call for CV", "", "needs_review"),
        ("jobalerts-noreply@linkedin.com", "Application deadline", "", "job_alert"),
        (
            "jobs-noreply@linkedin.com",
            "Notice",
            "your application was sent to X",
            "application_update",
        ),
        ("ps@dubai.bits-pilani.ac.in", "Update on Your Application", "", "application_update"),
        ("notifications@github.com", "Issue", "> Call for CV PS II", "dev_ops"),
        ("unknown@demo.invalid", "Question", "> You were shortlisted", "needs_review"),
        ("unknown@demo.invalid", "Question", "x" * 301 + " shortlisted", "needs_review"),
        ("f20990001@students.demo.invalid", "Call for CV help", "", "academic"),
    ],
)
def test_precedence_and_exact_matching(sender, subject, body, expected):
    result = classify(sender, subject, body)
    assert result.category == expected
    assert result.rule_id and result.reason
    assert result.source_quote in (sender, subject, body) or result.source_quote in body


def test_all_categories_and_quote_evidence():
    messages = [
        m
        for m in load(Path("fixtures/export_sample"), "synthetic")
        if m.provider_id.startswith(("P-D", "O-D"))
    ]
    results = [classify(m.sender, m.subject, m.body_text) for m in messages]
    assert {r.category for r in results} == set(CATEGORIES)
    for message, result in zip(messages, results, strict=True):
        assert result.source_quote in (message.sender, message.subject, message.body_text) or (
            result.source_quote in message.body_text
        )
        assert result.source_quote in result.reason


def test_urgency_without_inventing_dates():
    now = datetime.fromisoformat("2026-10-28T02:30:00+04:00")
    assert urgency("2026-10-28T08:00:00+04:00", now) == "high"
    assert urgency("2026-11-02T08:00:00+04:00", now) == "normal"
    assert urgency("2026-10-27T08:00:00+04:00", now) == "normal"
    assert urgency("2026-10-29", now) == "normal"
    assert urgency(None, now) == "normal"


@pytest.mark.parametrize(
    "sender,subject,body,expected",
    [
        ("Mira Sen <PS@DUBAI.BITS-PILANI.AC.IN>", "Call for CV", "", "ps_call"),
        ("ps@dubai.bits-pilani.ac.in", "Call for CV", "You were shortlisted", "ps_call"),
        ("psd@dubai.bits-pilani.ac.in", "Call for CV", "", "ps_admin"),
        (
            "jobs-noreply@linkedin.com",
            "Your application was sent to Moss Circuit",
            "",
            "application_update",
        ),
        ("ps@dubai.bits-pilani.ac.in", "Assignment survey", "", "ps_admin"),
        ("council@dubai.bits-pilani.ac.in", "Exam seating", "", "academic"),
        ("events@sub.easychair.org", "Discussion", "", "needs_review"),
        ("events@easychair.org.evil.invalid", "Discussion", "", "needs_review"),
        ("notifications@github.com.evil.invalid", "Issue", "", "needs_review"),
        ("noor@contacts.demo.invalid", "Invoice", "", "account_billing"),
        ("updates@product.demo.invalid", "New this month", "", "newsletter_promo"),
    ],
)
def test_remaining_collisions(sender, subject, body, expected):
    assert classify(sender, subject, body).category == expected


def test_contacts_configurable():
    assert (
        classify("friend@demo.invalid", "Lunch", "", ["friend@demo.invalid"]).category == "personal"
    )
    assert classify("noor@contacts.demo.invalid", "Lunch", "", []).category == "needs_review"


def test_body_quote_is_verbatim():
    body = "A short note. You were not shortlisted for this intake."
    prediction = classify("recruiter@demo.invalid", "Correspondence", body)
    assert prediction.category == "application_update"
    assert prediction.source_quote == "not shortlisted"
    assert prediction.source_quote in prediction.reason
