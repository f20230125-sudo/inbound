import re
from pathlib import Path


def test_no_outward_capabilities():
    forbidden = re.compile(
        r"\b(?:smtplib|sendmail|requests|httpx|webbrowser)\b|"
        r"urllib\.(?:request|urlopen)|socket\s*\.\s*(?:connect|create_connection)|"
        r"\.(?:connect_ex|getaddrinfo)\s*\(|gmail\.(?:send|modify|compose)|mail\.google\.com/"
    )
    for path in Path("inbound").rglob("*.py"):
        text = path.read_text("utf8")
        assert not forbidden.search(text), path
        if path != Path("inbound/packs/build.py"):
            assert not re.search(r"\bsubprocess\b|os\.(?:system|popen|spawn)", text), path
