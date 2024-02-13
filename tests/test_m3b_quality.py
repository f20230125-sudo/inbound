"""Public evidence + fictional JDs; no real mail or frozen fixture changes."""

import json
from copy import deepcopy
from dataclasses import replace
from itertools import combinations
from pathlib import Path

import pytest

from inbound.db import import_messages
from inbound.evidence.import_cv import parse_cv
from inbound.evidence.registry import store_registry
from inbound.extract.pipeline import extract_messages
from inbound.extract.roles import parse_roles
from inbound.packs.answers import answers
from inbound.packs.build import create_pack
from inbound.packs.rank import rank
from inbound.triage.rules import triage_messages
from tests.m2_helpers import CLOCK, message
from tests.m3_helpers import snapshot
from tests.test_import_cv import MANIFEST, TEXT

MULTI_ROLE_JD = """Job Title & JD
1. Pre-sales Intern
Requirements:
- Identify and develop lead lists
- Research potential clients
2. AI Developer Intern
Requirements:
- Develop AI/ML tools using Python
- Integrate LLMs and APIs
- Apply prompt engineering and held-out evaluation
- Build BM25 retrieval and automation
3. Software Developer Intern
Requirements:
- Build REST APIs using SQL
- Develop native iOS applications using Swift
- Maintain Android applications using Kotlin
4. Marketing Intern
Requirements:
- Plan influencer outreach
- Produce video campaigns
"""


def public_snapshot():
    return json.loads(Path("fixtures/evidence_snapshot.json").read_text(encoding="utf8"))


def fictional_opportunity(db, body=MULTI_ROLE_JD):
    original = message("P-D12")
    if not body.startswith("Job Title & JD"):
        body = "Job Title & JD\n" + body
    fictional = replace(
        original,
        provider_id="m3b-fictional",
        thread_id="m3b-fictional",
        subject="Call for CV - Lantern Labs,Dubai",
        body_text=body,
    )
    import_messages(db, [fictional])
    triage_messages(db)
    extract_messages(db, clock=lambda: CLOCK)
    return db.execute("SELECT id FROM opportunities").fetchone()[0]


def assert_distinct_claims(data, selection):
    from inbound.packs.claims import near_duplicate

    projects = {p["id"]: p for p in data["projects"]}
    for chosen in selection["projects"]:
        bullets = {b["id"]: b for b in projects[chosen["id"]]["bullets"]}
        for a, b in combinations(chosen["bullets"], 2):
            assert not near_duplicate(bullets[a]["text_plain"], bullets[b]["text_plain"])


def test_real_snapshot_multi_role_pack(database, tmp_path, monkeypatch):
    monkeypatch.setenv("INBOUND_DATA_ROOT", str(tmp_path / "data"))
    data = public_snapshot()
    store_registry(database, data)
    result = create_pack(database, fictional_opportunity(database))
    checks, selection = result["checks"], result["selection"]
    assert checks["passed"] and checks["pages"] == 1 and checks["overfull"] == 0
    assert selection["recommended_role"]["title"] == "AI Developer Intern"
    assert "coverage" in selection["recommended_role"]["reason"].lower()
    assert len(selection["other_roles"]) == 3
    assert all("gaps" in r["coverage"] for r in selection["other_roles"])
    assert all(p["why"] for p in selection["projects"])
    assert selection["skills"] and len(selection["also_built"]) <= 5
    assert_distinct_claims(data, selection)
    directory = Path(result["files"]["pdf"]).parent
    assert directory.parent == tmp_path / "data/packs"
    assert "AI Developer Intern | Lantern Labs" not in (directory / "profile.tex").read_text()
    assert checks["fit"] != "low"
    stored_role = database.execute(
        "SELECT title FROM roles WHERE id=(SELECT role_id FROM packs WHERE id=?)", (result["id"],)
    ).fetchone()[0]
    assert stored_role == "AI Developer Intern"
    groups = (directory / "skills.tex").read_text().count(r"\\")
    assert 1 <= groups <= 4


def test_sales_low_fit_still_builds_and_warns(database):
    store_registry(database, public_snapshot())
    oid = fictional_opportunity(
        database,
        "1. Sales Intern\nRequirements:\n"
        "- Identify and develop lead lists\n"
        "- Research potential clients\n",
    )
    result = create_pack(database, oid)
    assert result["status"] == "needs_review"
    for record in (result["selection"], result["checks"]):
        assert record["fit"] == "low"
        assert record["coverage"] == {"supported": 0, "total": 2, "ratio": 0.0}
        assert record["fit_reason"] == "No evidence for 2 of 2 requirements: consider skipping"
    assert result["selection"]["skills"]


def test_role_ties_keep_source_order_and_unknown_is_not_full_coverage(database):
    store_registry(database, public_snapshot())
    oid = fictional_opportunity(
        database, "1. Unknown Intern\n2. Python Intern\n- Python\n3. Another Intern\n- Python\n"
    )
    result = create_pack(database, oid)
    assert result["selection"]["recommended_role"]["title"] == "Python Intern"
    assert "order" in result["selection"]["recommended_role"]["reason"].lower()


def test_bullet_variants_prefer_manifest_unless_more_requirement_coverage():
    data = snapshot()
    p = data["projects"][0]
    preferred = deepcopy(p["bullets"][0])
    preferred.update(
        id="preferred",
        text_plain="Built Python tool on 40 held-out tasks",
        text_tex="Built Python tool on 40 held-out tasks",
        preferred=True,
    )
    alternate = {
        **preferred,
        "id": "alternate",
        "preferred": False,
        "text_plain": "Built Python SQL tool on 40 held-out tasks",
        "text_tex": "Built Python SQL tool on 40 held-out tasks",
    }
    p["bullets"] = [alternate, preferred]
    first = rank(data, ["Python"])
    assert next(s for s in first["projects"] if s["id"] == p["id"])["bullets"] == ["preferred"]
    second = rank(data, ["Python", "SQL"])
    assert next(s for s in second["projects"] if s["id"] == p["id"])["bullets"] == ["alternate"]


@pytest.mark.parametrize(
    "requirement",
    ["AI/ML", "LLMs", "APIs", "REST", "Python", "SQL", "prompt-engineering", "automation"],
)
def test_real_alias_and_bullet_requirement_links(requirement):
    selection = rank(public_snapshot(), [requirement])
    assert selection["coverage"]["supported"] == 1
    assert any(p["why"] for p in selection["projects"])
    assert selection["skills"]


def test_snapshot_claims_and_also_built_relevance():
    data = public_snapshot()
    for requirements in (["internal dashboard", "reconciliation checks"], ["BM25", "Python"]):
        selected = rank(data, requirements)
        assert_distinct_claims(data, selected)
        assert len(selected["also_built"]) <= 5
    # Force a relevant fifth project and confirm Also built is ordered by relevance.
    demo = snapshot()
    for i, p in enumerate(demo["projects"]):
        p["id"] = f"z{i}"
        for b in p["bullets"]:
            b["text_plain"] = "unrelated"
    for i in range(6):
        p = deepcopy(demo["projects"][0])
        p["id"] = f"extra{i}"
        for j, b in enumerate(p["bullets"]):
            b.update(id=f"extra{i}-{j}", text_plain="BM25 retrieval")
        demo["projects"].append(p)
    selected = rank(demo, ["BM25 retrieval"])
    assert selected["also_built"][:2] == ["extra4", "extra5"]


def test_wrapped_bullets_join_without_swallowing_headings_or_sentences():
    text = """1. Sales Intern
Requirements:
- Identify property management companies, hospitality groups, and
  prospective clients across the fictional region
- Research potential clients.
Responsibilities:
- Prepare lead lists and
  track outreach
Qualifications
2. AI Intern
- Evaluate LLMs.
An unrelated complete sentence.
Conditions:
- Must be available
"""
    roles = parse_roles(text, "", "wrapped")["normalized"]
    assert [q["text"] for q in roles[0]["requirements"]] == [
        (
            "Identify property management companies, hospitality groups, and prospective clients "
            "across the fictional region"
        ),
        "Research potential clients.",
        "Prepare lead lists and track outreach",
    ]
    assert [q["text"] for q in roles[1]["requirements"]] == ["Evaluate LLMs."]


def test_cv_heading_pitch_imported_and_registry_purpose_wins():
    project = parse_cv(TEXT, "first.tex", MANIFEST)[0]
    assert project["pitch"] == "purpose"
    data = {"projects": [project]}
    selection = {"projects": [{"id": project["id"]}]}
    assert answers(data, selection)[0]["purpose"] == "purpose"
    project["tagline"] = "Registry purpose"
    assert answers(data, selection)[0]["purpose"] == "Registry purpose"


def test_application_instructions_are_not_requirement_continuations():
    text = (
        "1. Backend Intern\nRequirements:\n- Python\n- SQL\n"
        "Please apply directly through the fictional careers page.\n"
    )
    roles = parse_roles(text, "", "fictional")["normalized"]
    assert [q["text"] for q in roles[0]["requirements"]] == ["Python", "SQL"]


def test_empty_portfolio_pitch_preserves_cv_heading_pitch():
    from inbound.evidence.import_projects import merge_projects

    project = parse_cv(TEXT, "first.tex", MANIFEST)[0]
    data = merge_projects({"projects": [project]}, [{"id": "one", "pitch": ""}])
    assert answers(data, {"projects": [{"id": "one"}]})[0]["purpose"] == "purpose"


def test_existing_registry_looks_up_approved_cv_heading_when_purpose_missing(tmp_path, monkeypatch):
    import importlib

    from inbound.evidence.import_cv import heading_pitch_from_cv

    module = importlib.import_module("inbound.packs.answers")
    manifest = {**MANIFEST, "source_root": str(tmp_path)}
    (tmp_path / "first.tex").write_bytes(TEXT.encode("utf8"))
    project = parse_cv(TEXT, "first.tex", MANIFEST)[0]
    project["pitch"] = project["heading_pitch"] = ""
    monkeypatch.setattr(
        module, "heading_pitch_from_cv", lambda p: heading_pitch_from_cv(p, manifest)
    )
    data = {"scope": "public", "projects": [project]}
    selection = {"projects": [{"id": "one"}]}
    assert answers(data, selection)[0]["purpose"] == "purpose"
    project["source_hash"] = "0" * 64
    assert answers(data, selection)[0]["purpose"] == "Uzair: what is this project for?"


def test_low_fit_threshold_is_below_one_quarter():
    data = public_snapshot()
    unknown = ["krypton", "zebrium", "xenolite", "qwertyx"]
    assert rank(data, ["Python", *unknown])["fit"] == "low"
    assert rank(data, ["Python", *unknown[:3]])["fit"] == "supported"


def test_known_real_variants_are_same_claim_and_distinct_achievements_stay_distinct():
    from inbound.packs.claims import claims, near_duplicate

    projects = {p["id"]: p for p in public_snapshot()["projects"]}
    order = projects["order-desk"]["bullets"]
    signal = projects["signaldesk-ai"]["bullets"]
    assert near_duplicate(order[0]["text_plain"], order[3]["text_plain"])
    assert near_duplicate(signal[0]["text_plain"], signal[2]["text_plain"])
    assert not near_duplicate("Built a Python REST API", "Evaluated BM25 on 40 held-out tasks")
    groups = claims(signal)
    assert len(groups) == 1  # The preferred composite bridges both narrower variants.


def test_skills_match_first_then_project_fallback_with_line_cap():
    from inbound.packs.rank import compact_skills

    skills = [
        {"id": "generic", "name": "Python", "category": "languages", "projects": ["p"]},
        {"id": "match", "name": "BM25", "category": "ai", "projects": ["p"]},
    ]
    assert compact_skills(skills, {"match"}, {"p"}) == ["match", "generic"]
    assert compact_skills(skills, set(), {"p"}, max_lines=1) == ["generic"]
    assert compact_skills(skills, set(), set())  # Approved registry still yields skills.


def test_explicit_settings_controls_pack_directory_and_rejects_escape(
    database, tmp_path, monkeypatch
):
    from inbound.settings import Settings
    from tests.m3_helpers import opportunity

    monkeypatch.setenv("INBOUND_DATA_ROOT", str(tmp_path / "environment-data"))
    configured = Settings(data_root=tmp_path / "explicit-data")
    oid = opportunity(database)
    result = create_pack(database, oid, demo=True, settings=configured)
    assert Path(result["files"]["pdf"]).parent.parent == configured.data_root / "packs"
    with pytest.raises(ValueError, match="data root"):
        create_pack(database, oid, demo=True, settings=configured, pack_root=tmp_path / "escape")
    assert not (tmp_path / "escape").exists()
