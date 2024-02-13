import hashlib
import json
from pathlib import Path

from inbound.packs.build import create_pack
from tests.m3_helpers import opportunity


def hashes():
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path("D:/claude-workspace/cv-msd/fresh").glob("*.tex"))
    }


def test_every_cv_source_unchanged_after_build(database):
    before = hashes()
    assert before
    create_pack(database, opportunity(database), demo=True)
    after = hashes()
    Path(".local/reports").mkdir(parents=True, exist_ok=True)
    Path(".local/reports/m3-cv-hashes.json").write_text(
        json.dumps({"before": before, "after": after, "unchanged": before == after}, indent=2),
        encoding="utf8",
    )
    assert before == after
