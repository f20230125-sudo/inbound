from inbound.packs.answers import answers
from inbound.packs.rank import rank
from tests.m3_helpers import snapshot


def test_answers_only_registry_facts_and_capped():
    data = snapshot()
    selection = rank(data, ["Python"])
    result = answers(data, selection, limit=120)
    assert len(result) == 4
    assert all(len(value) <= 120 for row in result for key, value in row.items() if key != "id")
    for row in result:
        p = next(p for p in data["projects"] if p["id"] == row["id"])
        assert row["purpose"] == p["tagline"][:120]
        assert row["challenge_fix"] == p["decisions"][0][:120]
    for p in data["projects"]:
        p["decisions"] = []
    assert all("Uzair" in row["challenge_fix"] for row in answers(data, selection))
