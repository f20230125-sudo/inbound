"""Idempotent registry writes, stable content IDs, explicit approval scopes."""

import json
from pathlib import Path

from inbound.pause import check
from inbound.settings import REPO


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def store_registry(db, data):
    check(db)
    scope = data["scope"]
    if scope not in {"public", "demo"}:
        raise ValueError("Unknown registry scope")
    with db:
        # Deactivate withdrawn evidence, preserving historical IDs for existing packs.
        db.execute(
            "UPDATE evidence_bullets SET active=0 WHERE project_id IN "
            "(SELECT id FROM evidence_projects WHERE scope=?)",
            (scope,),
        )
        for table in ("evidence_projects", "skills"):
            db.execute(f"UPDATE {table} SET active=0 WHERE scope=?", (scope,))
        for p in data["projects"]:
            check(db)
            expected_demo = p["id"].startswith("demo-")
            if expected_demo != (scope == "demo"):
                raise ValueError("Evidence scope collision")
            facts = {k: v for k, v in p.items() if k != "bullets"}
            db.execute(
                "INSERT INTO evidence_projects VALUES (?,?,?,?,?,?,?,?,?,?,1) "
                "ON CONFLICT(id) DO UPDATE SET title=excluded.title,stack_json=excluded.stack_json,"
                "live_url=excluded.live_url,code_url=excluded.code_url,source_file=excluded.source_file,"
                "source_hash=excluded.source_hash,as_of=excluded.as_of,facts_json=excluded.facts_json,"
                "active=1",
                (
                    p["id"],
                    p["title"],
                    dump(p["stack"]),
                    p.get("live_url"),
                    p.get("code_url"),
                    p.get("source_file"),
                    p.get("source_hash"),
                    p.get("as_of"),
                    scope,
                    dump(facts),
                ),
            )
            for ordinal, b in enumerate(p["bullets"]):
                db.execute(
                    "INSERT INTO evidence_bullets VALUES (?,?,?,?,?,?,?,?,1,?) "
                    "ON CONFLICT(id) DO UPDATE SET text_tex=excluded.text_tex,"
                    "text_plain=excluded.text_plain,source_file=excluded.source_file,"
                    "source_line=excluded.source_line,source_hash=excluded.source_hash,"
                    "preferred=excluded.preferred,active=1,ordinal=excluded.ordinal",
                    (
                        b["id"],
                        p["id"],
                        b["text_tex"],
                        b["text_plain"],
                        b["source_file"],
                        b["source_line"],
                        b["source_hash"],
                        int(b.get("preferred", False)),
                        ordinal,
                    ),
                )
        known = {p["id"] for p in data["projects"]}
        for s in data["skills"]:
            if s["id"].startswith("demo-") != (scope == "demo"):
                raise ValueError("Skill scope collision")
            db.execute(
                "INSERT INTO skills VALUES (?,?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET "
                "name=excluded.name,aliases_json=excluded.aliases_json,category=excluded.category,"
                "approved=excluded.approved,facts_json=excluded.facts_json,active=1",
                (
                    s["id"],
                    s["name"],
                    dump(s["aliases"]),
                    scope,
                    s.get("category", "engineering"),
                    int(s.get("approved") is True),
                    dump(s),
                ),
            )
            db.execute("DELETE FROM skill_evidence WHERE skill_id=?", (s["id"],))
            for project in s.get("projects", []):
                if project in known:
                    db.execute(
                        "INSERT INTO skill_evidence VALUES (?,?,?,?)",
                        (s["id"], project, s.get("note", ""), int(s.get("approved") is True)),
                    )
        metadata = {k: v for k, v in data.items() if k not in ("projects", "skills")}
        db.execute(
            "INSERT INTO evidence_snapshots VALUES (?,?) ON CONFLICT(scope) "
            "DO UPDATE SET metadata_json=excluded.metadata_json",
            (scope, dump(metadata)),
        )


def load_registry(db, scope):
    row = db.execute(
        "SELECT metadata_json FROM evidence_snapshots WHERE scope=?", (scope,)
    ).fetchone()
    if row is None:
        raise ValueError("Import evidence before building a pack")
    data = json.loads(row[0])
    data["projects"] = []
    for row in db.execute(
        "SELECT * FROM evidence_projects WHERE scope=? AND active=1 ORDER BY rowid", (scope,)
    ):
        p = json.loads(row["facts_json"])
        p["bullets"] = [
            {
                k: b[k]
                for k in (
                    "id",
                    "text_tex",
                    "text_plain",
                    "source_file",
                    "source_line",
                    "source_hash",
                    "preferred",
                )
            }
            for b in db.execute(
                "SELECT * FROM evidence_bullets WHERE project_id=? AND active=1 ORDER BY ordinal",
                (row["id"],),
            )
        ]
        for b in p["bullets"]:
            b["preferred"] = bool(b["preferred"])
        data["projects"].append(p)
    data["skills"] = [
        json.loads(s[0])
        for s in db.execute(
            "SELECT facts_json FROM skills WHERE scope=? AND active=1 ORDER BY rowid", (scope,)
        )
    ]
    return data


def import_evidence(db, demo=False):
    check(db)
    if demo:
        data = json.loads((REPO / "fixtures/demo_evidence.json").read_text("utf8"))
    else:
        from inbound.evidence.import_cv import import_cv
        from inbound.evidence.import_projects import merge_projects, parse_projects
        from inbound.evidence.skills import load_skills

        data = import_cv()
        check(db)
        source = Path("D:/claude-workspace/portfolio-os/src/knowledge/projects.ts")
        data = merge_projects(data, parse_projects(source.read_text("utf8")))
        data["skills"] = load_skills()
    check(db)
    store_registry(db, data)
    return data
