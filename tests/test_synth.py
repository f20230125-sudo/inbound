import hashlib
import json
from collections import Counter
from pathlib import Path

from synth.families import render
from synth.generate import generate


def test_frozen_counts_and_groups():
    cases = json.loads(Path("synth/cases.json").read_text(encoding="utf-8"))["cases"]
    assert len(cases) == len({c["id"] for c in cases}) == 190
    assert Counter(c["split"] for c in cases) == {"dev": 64, "held-out": 116, "attack": 10}
    groups = {}
    for case in cases:
        assert case["gold"]["category"]
        groups.setdefault(case["group"], set()).add(case["split"])
        for field in case["gold"]["fields"].values():
            assert {"raw", "normalized", "status", "source_text"} <= field.keys()
    assert all(len(splits) == 1 for splits in groups.values())
    h25 = next(c for c in cases if c["id"] == "P-H25")
    assert h25["gold"]["fields"]["stipend"]["status"] == "unknown"
    assert h25["gold"]["fields"]["stipend"]["source_text"] == "· As per company norms"


def test_deterministic_bytes_and_manifest(tmp_path):
    generate(tmp_path)
    first = {
        p.relative_to(tmp_path).as_posix(): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    generate(tmp_path)
    assert first == {
        p.relative_to(tmp_path).as_posix(): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset"] == "r4-20261028-01"
    assert manifest["counts"] == {"dev": 64, "held-out": 116, "attack": 10}
    assert len(manifest["eml_alternates"]) == 5
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256(first[name]).hexdigest() == digest
        assert first[name] == (Path("fixtures") / name).read_bytes()


def test_frozen_family_counts_and_canonical_alternates():
    cases = json.loads(Path("synth/cases.json").read_text(encoding="utf-8"))["cases"]
    ps = [c for c in cases if c["id"].startswith("P-")]
    assert Counter(c["family"] for c in ps) == {
        "A": 14,
        "B": 9,
        "C": 5,
        "D": 7,
        "E": 7,
        "F": 7,
        "G": 6,
        "H": 5,
    }
    assert Counter(c["gold"]["category"] for c in ps) == {
        "ps_call": 49,
        "ps_admin": 6,
        "application_update": 5,
    }
    calls = [c for c in ps if c["gold"]["category"] == "ps_call"]
    assert len({c["group"] for c in calls}) == 40
    assert sum(c["gold"]["creates_opportunity"] for c in calls) == 40


def test_source_facts_and_missing_jd_requirements():
    cases = json.loads(Path("synth/cases.json").read_text(encoding="utf-8"))["cases"]
    by_id = {c["id"]: c for c in cases}
    for identity in (
        "P-D05",
        "P-D16",
        "P-D17",
        "P-D20",
        "P-H06",
        "P-H16",
        "P-H24",
        "P-H25",
        "P-H28",
        "P-H29",
    ):
        roles = by_id[identity]["gold"]["fields"]["roles"]["normalized"]
        assert roles and all(r["requirements"] is None for r in roles)
    assert "· As per company norms" in render(by_id["P-H25"])
    assert by_id["P-H10"]["message"]["sent_at"] == "2026-10-27T20:15:00+00:00"
    assert by_id["P-H10"]["message"]["received_at"] == "2026-10-27T21:45:00+00:00"
    assert by_id["P-H14"]["gold"]["fields"]["deadline"]["status"] == "conflicting"
    assert by_id["P-H33"]["gold"]["fields"]["admin_deadline"]["status"] == "conflicting"
    assert by_id["P-H08"]["gold"]["fields"]["role_count"]["normalized"] is None


def test_gold_provenance_quotes_and_attack_denominators():
    cases = json.loads(Path("synth/cases.json").read_text(encoding="utf-8"))["cases"]
    for case in cases:
        for value in case["gold"]["fields"].values():
            assert value["provenance"]["message_id"]
            if value["status"] == "unknown":
                assert value["missing_reason"]
            if value["status"] == "conflicting":
                assert len(value["candidates"]) == 2
                assert all(c["source_text"] for c in value["candidates"])
    attacks = [c for c in cases if c["split"] == "attack"]
    assert Counter(c["gold"]["attack"]["kind"] for c in attacks) == {
        "instruction_or_sender": 8,
        "source_fact": 2,
    }
    assert all(c["gold"]["attack"]["outward_actions"] == 0 for c in attacks)


def test_gold_quotes_are_present_in_authored_sources():
    definitions = json.loads(Path("synth/cases.json").read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in definitions["cases"]}
    for case in definitions["cases"]:
        for name, value in case["gold"]["fields"].items():
            if not value["source_text"] or value.get("observations"):
                continue
            origin = value["provenance"]
            source = by_id[origin["message_id"]]
            if origin.get("source") == "attachment":
                text = source["attachment_plan"]["text"]
            else:
                text = source["message"]["subject"] + "\n" + render(source)
            assert value["source_text"] in text, (case["id"], name, value["source_text"])
