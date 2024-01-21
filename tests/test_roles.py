import pytest

from inbound.extract.roles import parse_roles


@pytest.mark.parametrize(
    "heading", ["*1. Backend Intern*", "(1) Backend Intern", "Role 1: Backend Intern"]
)
def test_requirements_stay_with_role(heading):
    text = heading + "\nExpected Skills:\n· Python\n· Flask\n*2. Test Intern*\n· pytest"
    roles = parse_roles(text, "", "sample")["normalized"]
    assert [r["title"] for r in roles] == ["Backend Intern", "Test Intern"]
    assert [[q["text"] for q in r["requirements"]] for r in roles] == [
        ["Python", "Flask"],
        ["pytest"],
    ]


def test_subject_only_and_unknown():
    roles = parse_roles("", "Call for CV - Company,City - QA Intern", "sample")
    assert roles["normalized"][0]["requirements"] is None
    assert roles["normalized"][0]["title"] == "QA Intern"
    assert roles["normalized"][0]["requirements_status"] == "unknown"
    assert parse_roles("", "Call for CV - Company,City", "sample")["status"] == "unknown"


def test_plain_jd_title_and_inline_requirements():
    roles = parse_roles("Backend Intern\nRequirements: Python; Flask; SQL", "", "sample")
    assert [q["text"] for q in roles["normalized"][0]["requirements"]] == ["Python", "Flask", "SQL"]


@pytest.mark.parametrize(
    "text",
    [
        "Role | Requirements\nBackend Intern | Python; Flask\nTest Intern | pytest",
        "(1) Backend Intern Requirements: Python; Flask (2) Test Intern Requirements: pytest",
        "(1) Backend Intern\nRequirements: Python; SQLite\nFTS5; BM25\n(2) Test Intern\nRequirements: pytest",
    ],
)
def test_tables_paragraph_numbering_and_continuation(text):
    roles = parse_roles(text, "", "example")["normalized"]
    assert [r["title"] for r in roles] == ["Backend Intern", "Test Intern"]
    assert roles[1]["requirements"] == [{"id": "example-r2-q1", "text": "pytest"}]
    assert len(roles[0]["requirements"]) >= 2
    assert roles[0]["requirements"][0]["text"] == "Python"
    if "FTS5" in text:
        assert roles[0]["requirements"][1]["text"] == "SQLite FTS5"
