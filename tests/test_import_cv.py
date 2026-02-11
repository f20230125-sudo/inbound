from copy import deepcopy

from inbound.evidence.import_cv import import_cv, parse_cv, plain_text
from inbound.evidence.registry import load_registry, store_registry

MANIFEST = {
    "projects": {"one": {"preferred": "first.tex", "also": ["second.tex"]}},
    "heading_map": {"One": "one", "Excluded": "excluded"},
}
TEXT = r"""\resumeProjectHeading{\textbf{One: purpose} $|$ \emph{Python, SQL}}
{\link{\onelive}{Live}}
\resumeItem{Built \textbf{nested {safe}} text with 90\% and \& SQL.}
\resumeItem{Built \textbf{nested {safe}} text with 90\% and \& SQL.}
% \resumeProjectHeading{\textbf{One}}{} \resumeItem{commented}
\resumeProjectHeading{\textbf{Excluded: no approval}}{}
\resumeItem{Must never import.}
\resumeProjectHeading{\textbf{Also built: One}}{}
\resumeItem{Also must never import.}
"""


def test_nested_macros_skips_comments_dedupe():
    projects = parse_cv(TEXT, "first.tex", MANIFEST, {"onelive": "https://one.invalid"})
    assert len(projects) == 1
    p = projects[0]
    assert p["id"] == "one" and p["stack"] == ["Python", "SQL"]
    assert p["live_url"] == "https://one.invalid"
    assert len(p["bullets"]) == 1
    b = p["bullets"][0]
    assert b["text_plain"] == "Built nested safe text with 90% and & SQL."
    assert r"\textbf{nested {safe}}" in b["text_tex"]
    assert b["source_line"] == 3 and len(b["source_hash"]) == 64
    assert plain_text(r"\href{https://x.invalid}{\emph{linked}}") == "linked"


def test_preferred_order_stable_ids_and_missing_project(tmp_path, database):
    (tmp_path / "first.tex").write_text(TEXT, encoding="utf8")
    (tmp_path / "second.tex").write_text(TEXT.replace("Built ", "Other "), encoding="utf8")
    manifest = deepcopy(MANIFEST)
    manifest["source_root"] = str(tmp_path)
    manifest["fixed"] = {"preamble": "preamble.tex"}
    (tmp_path / "preamble.tex").write_text("", encoding="utf8")
    data = import_cv(manifest)
    bullets = data["projects"][0]["bullets"]
    assert [b["source_file"] for b in bullets] == ["first.tex", "second.tex"]
    assert bullets[0]["preferred"] and not bullets[1]["preferred"]
    data["skills"] = []
    store_registry(database, data)
    store_registry(database, data)
    assert load_registry(database, "public")["projects"] == data["projects"]
    assert database.execute("SELECT count(*) FROM evidence_bullets").fetchone()[0] == 2


def test_reimport_withdrawals_and_scope_isolation(database):
    import json
    from pathlib import Path

    from tests.m3_helpers import snapshot

    public = json.loads(Path("fixtures/evidence_snapshot.json").read_text(encoding="utf8"))
    demo = snapshot()
    store_registry(database, public)
    store_registry(database, demo)
    assert load_registry(database, "public") == public
    assert load_registry(database, "demo") == demo
    withdrawn = deepcopy(public)
    removed = withdrawn["projects"].pop()
    store_registry(database, withdrawn)
    assert removed["id"] not in {p["id"] for p in load_registry(database, "public")["projects"]}
    assert load_registry(database, "demo") == demo
    assert (
        database.execute(
            "SELECT active FROM evidence_projects WHERE id=?", (removed["id"],)
        ).fetchone()[0]
        == 0
    )
