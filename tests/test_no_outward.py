import re
from pathlib import Path

GMAIL = Path("inbound/sources/gmail_api.py")


def test_no_outward_capabilities():
    forbidden = re.compile(
        r"\b(?:smtplib|sendmail|requests|httpx|webbrowser)\b|"
        r"urllib\.(?:request|urlopen)|socket\s*\.\s*(?:connect|create_connection)|"
        r"\.(?:connect_ex|getaddrinfo)\s*\(|gmail\.(?:send|modify|compose)|mail\.google\.com/"
    )
    for path in Path("inbound").rglob("*.py"):
        text = path.read_text("utf8")
        if path == GMAIL:
            # The one read-only networking exception (SPEC Amendment 3a): httpx is allowed
            # here; sending or modifying mail is not.
            text = re.sub(r"\bhttpx\b", "", text)
        assert not forbidden.search(text), path
        if path != Path("inbound/packs/build.py"):
            assert not re.search(r"\bsubprocess\b|os\.(?:system|popen|spawn)", text), path


def test_gmail_is_read_only():
    from inbound.sources import gmail_api

    assert gmail_api.SCOPE == "https://www.googleapis.com/auth/gmail.readonly"
    assert gmail_api.ALLOWED == {
        ("POST", "oauth2.googleapis.com"),
        ("GET", "gmail.googleapis.com"),
    }
    scopes = re.compile(
        r"gmail\.(?:send|modify|compose|insert|labels|metadata)|auth/gmail(?!\.readonly)|"
        r"https://mail\.google\.com/"
    )
    for path in Path("inbound").rglob("*.py"):
        assert not scopes.search(path.read_text("utf8")), path
    # Gmail API write endpoints never appear in the two modules that talk to Gmail.
    endpoints = re.compile(
        r"/send\b|batchModify|batchDelete|/trash\b|/untrash\b|/import\b|/insert\b|/drafts\b|"
        r"/modify\b|/labels\b"
    )
    for path in (GMAIL, Path("inbound/gmail_sync.py")):
        assert not endpoints.search(path.read_text("utf8")), path
