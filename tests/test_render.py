from copy import deepcopy
from pathlib import Path

import pytest

from inbound.packs.rank import rank
from inbound.packs.render import RenderBlocked, escape_tex, render
from tests.m3_helpers import snapshot


def test_injection_escaped_and_demo_identity_replaced(tmp_path):
    data = snapshot()
    attack = r"X & % $ # _ { } ~ ^ \input{private/secret}"
    selection = rank(data, [attack])
    result = render(tmp_path, data, selection, company=attack, role=attack, demo=True)
    text = "\n".join(p.read_text(encoding="utf8") for p in tmp_path.glob("*.tex"))
    assert attack not in text and escape_tex(attack) in text
    assert "Mohammad" not in text and "Amaani" not in text and "IEEE" not in text
    assert "Sara Qamar" in text and "Lumen Bay Institute of Computing" in text
    assert "github.com" not in text and "vercel.app" not in text
    assert result["identity"] == "Sara Qamar"
    assert text.count(r"\end{document}") == 1


def test_fixed_hash_mismatch_blocks_before_copy(tmp_path):
    data = snapshot()
    data["scope"] = "public"
    fixed = {
        "source_root": str(tmp_path),
        "files": {"preamble": {"file": "changed.tex", "sha256": "0" * 64}},
    }
    (tmp_path / "changed.tex").write_text("changed", encoding="utf8")
    with pytest.raises(RenderBlocked, match="hash"):
        render(
            tmp_path / "pack",
            data,
            rank(data, []),
            company="Demo",
            role="API",
            demo=False,
            fixed=fixed,
        )
    assert not (tmp_path / "pack" / "preamble.tex").exists()


def test_registry_ids_and_approval_enforced(tmp_path):
    data = snapshot()
    selection = rank(data, [])
    bad = deepcopy(selection)
    bad["projects"][0]["bullets"] = ["invented"]
    with pytest.raises(ValueError):
        render(tmp_path, data, bad, company="Demo", role="API", demo=True)
    data["skills"][0]["approved"] = False
    selection["skills"] = [data["skills"][0]["id"]]
    with pytest.raises(ValueError):
        render(tmp_path, data, selection, company="Demo", role="API", demo=True)


def test_public_snapshot_contains_only_project_and_skill_evidence():
    import json

    data = json.loads(Path("fixtures/evidence_snapshot.json").read_text(encoding="utf8"))
    assert data["scope"] == "public" and data["projects"] and data["skills"]
    assert "applicant" not in data
    assert all(
        b["source_file"].endswith("-body.tex") for p in data["projects"] for b in p["bullets"]
    )
    assert "footnote" not in {p["id"] for p in data["projects"]}


def test_fixed_parts_verbatim_order_and_approved_profile(tmp_path):
    import hashlib

    from inbound.packs.rank import select_profile

    data = snapshot()
    data["scope"] = "public"
    source = tmp_path / "source"
    source.mkdir()
    fixed = {
        "source_root": str(source),
        "files": {},
        "order": ["preamble", "head", "profile", "projects", "tail", "skills"],
        "default_filename": "Synthetic-{company}.pdf",
        "identity_line_check": "Fictional",
        "certification": "Approved fictional certification",
    }
    for name, content in [
        ("preamble", b"% approved preamble\r\n"),
        ("head", b"\\begin{document}\nFictional\n"),
        ("tail", b"% approved experience/research\r\n"),
    ]:
        (source / (name + ".tex")).write_bytes(content)
        fixed["files"][name] = {
            "file": name + ".tex",
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    directory = tmp_path / "pack"
    selection = rank(data, ["SQL"])
    result = render(directory, data, selection, company="Demo", role="Data", fixed=fixed)
    assert result["filename"] == "Synthetic-Demo.pdf"
    for name in fixed["files"]:
        assert (directory / (name + ".tex")).read_bytes() == (source / (name + ".tex")).read_bytes()
    assert (directory / "body.tex").read_text().splitlines() == [
        r"\input{" + name + ".tex}" for name in fixed["order"]
    ]
    assert select_profile(["SQL"])["text"] in (directory / "profile.tex").read_text()
    assert (directory / "skills.tex").read_text().rstrip().endswith(r"\end{document}")


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "file:///secret", "https://safe.invalid/}{\\input{secret}}"]
)
def test_unsafe_evidence_links_block(tmp_path, url):
    data = snapshot()
    data["projects"][0]["code_url"] = url
    with pytest.raises(ValueError, match="URL"):
        render(tmp_path, data, rank(data, ["Flask"]), company="Demo", role="API", demo=True)
