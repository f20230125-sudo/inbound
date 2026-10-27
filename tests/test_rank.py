from copy import deepcopy

import pytest

from inbound.packs.rank import model_rank, rank, select_profile
from tests.m3_helpers import snapshot


def test_determinism_coverage_gaps_and_approved_skills():
    data = snapshot()
    data["skills"].append(
        {
            "id": "bad",
            "name": "Kubernetes",
            "approved": False,
            "aliases": [],
            "projects": ["demo-p1"],
        }
    )
    reqs = ["Docker", "Linux", "CI/CD", "Kubernetes", "SQL window functions"]
    a = rank(data, reqs)
    assert a == rank(deepcopy(data), reqs)
    assert len(a["projects"]) == 4
    assert {"demo-p5", "demo-p3"} <= {p["id"] for p in a["projects"]}
    assert a["gaps"] == [{"id": "q4", "text": "Kubernetes"}]
    assert "bad" not in a["skills"]
    assert all(1 <= len(p["bullets"]) <= 3 for p in a["projects"])
    assert sum(a["line_costs"].values()) <= 24
    assert model_rank(data, reqs)["status"] == "not run"


def test_line_budget_is_enforced():
    with pytest.raises(ValueError, match="budget"):
        rank(snapshot(), ["Python"], line_budget=1)


def test_profile_review_and_no_tailored_family():
    assert select_profile(["LLM"])["needs_uzair_review"]
    assert select_profile(["SQL"])["family"] == "data"
    assert select_profile(["unmatchedrole"])["not_tailored"]


def test_unknown_requirements_keep_approved_general_skills_without_inventing_requirements():
    data = snapshot()
    selection = rank(data, None)
    assert selection["skills"]
    assert selection["requirements"] == selection["gaps"] == []
    selected = {p["id"] for p in selection["projects"]}
    for identity in selection["skills"]:
        skill = next(s for s in data["skills"] if s["id"] == identity)
        assert skill["approved"] is True and selected.intersection(skill["projects"])
