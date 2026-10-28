"""The eight pre-frozen pack cases; human support labels never come from the ranker."""

import json
from contextlib import closing
from pathlib import Path
from time import perf_counter

from inbound.db import connect, import_messages
from inbound.extract.pipeline import extract_messages
from inbound.ledger import run
from inbound.packs.build import create_pack, set_status
from inbound.pause import check
from inbound.settings import REPO
from inbound.sources.export_txt import load
from inbound.triage.rules import triage_messages

# Transcribed from synth-cases-r4.md §4, independent of parser/ranker output.
HUMAN_SUPPORT = {
    "React": ["demo-p2"],
    "TypeScript": ["demo-p2"],
    "accessible HTML/CSS": ["demo-p2"],
    "Python": ["demo-p1", "demo-p3", "demo-p4", "demo-p5"],
    "Flask": ["demo-p1", "demo-p5"],
    "SQL": ["demo-p1", "demo-p3", "demo-p4"],
    "SQL window functions": ["demo-p3"],
    "CSV validation": ["demo-p3"],
    "SQLite FTS5": ["demo-p4"],
    "BM25": ["demo-p4"],
    "Docker": ["demo-p5"],
    "Linux": ["demo-p5"],
    "CI/CD": ["demo-p5"],
    "pytest": ["demo-p1", "demo-p3", "demo-p4"],
    "Vitest": ["demo-p2"],
    "Kubernetes": [],
    "PyTorch": [],
    "TensorFlow": [],
    "Flutter": [],
    "Dart": [],
}
PROVISIONAL = {"P-D16", "P-H28"}


def score(lines, projects):
    supported = sum(bool(set(HUMAN_SUPPORT[q["text"]]) & set(projects)) for q in lines)
    denominator = sum(bool(HUMAN_SUPPORT[q["text"]]) for q in lines)
    return {
        "supported": supported,
        "denominator": denominator,
        "coverage": supported / denominator if denominator else None,
        "unsupported_requirements": [q["id"] for q in lines if not HUMAN_SUPPORT[q["text"]]],
    }


def evaluate(db, report_dir=None, *, settings=None):
    check(db)
    definitions = json.loads((REPO / "synth/cases.json").read_text("utf8"))
    subset = definitions["pack_subset"]
    cases = {c["id"]: c for c in definitions["cases"]}
    import_messages(
        db,
        [m for m in load(REPO / "fixtures/export_sample", "synthetic") if m.provider_id in subset],
    )
    triage_messages(db)
    from datetime import datetime

    extract_messages(db, clock=lambda: datetime.fromisoformat(definitions["clock"]))
    results = []
    all_labels, baseline_supported, ranked_supported = 0, 0, 0
    for identity in subset:
        check(db)
        start = perf_counter()
        result = {
            "case": identity,
            "expected_provisional": identity in PROVISIONAL,
            "built": False,
            "passed": False,
        }
        # Gold recommended role is the first role in each frozen case (manifest §5).
        gold_roles = cases[identity]["gold"]["fields"]["roles"]["normalized"] or []
        labels = (gold_roles[0]["requirements"] or []) if gold_roles else []
        baseline = score(labels, ["demo-p1", "demo-p2", "demo-p3", "demo-p4"])
        baseline_supported += baseline["supported"]
        result["baseline"] = baseline
        opportunity = db.execute(
            "SELECT r.opportunity_id FROM opportunity_revisions r "
            "JOIN messages m ON m.id=r.message_id WHERE m.provider_id=?",
            (identity,),
        ).fetchone()
        try:
            if opportunity is None:
                raise ValueError("Frozen opportunity missing")
            pack = create_pack(db, opportunity[0], demo=True, settings=settings)
            projects = [p["id"] for p in pack["selection"]["projects"]]
            ranked = score(labels, projects)
            result.update(
                built=True,
                checks=pack["checks"],
                pack_id=pack["id"],
                selection=pack["selection"],
                baseline=baseline,
                deterministic=ranked,
            )
            ranked_supported += ranked["supported"]
            handling = pack["checks"]["provisional"] == (identity in PROVISIONAL)
            if identity in PROVISIONAL:
                try:
                    set_status(db, pack["id"], "reviewed")
                except ValueError:
                    result["review_without_acknowledgement_rejected"] = True
                else:
                    result["review_without_acknowledgement_rejected"] = False
                    handling = False
            result["passed"] = pack["checks"]["passed"] and handling
        except Exception as exc:  # noqa: BLE001 - retain every failed frozen case in the denominator
            # Retain the case and its gold denominator; persist no untrusted exception text.
            result["error"] = type(exc).__name__
        all_labels += sum(bool(HUMAN_SUPPORT[q["text"]]) for q in labels)
        result["seconds"] = round(perf_counter() - start, 4)
        results.append(result)
    report = {
        "denominator": len(subset),
        "normal_denominator": 6,
        "provisional_denominator": 2,
        "built": sum(c["built"] for c in results),
        "normal_passed": sum(c["passed"] and not c["expected_provisional"] for c in results),
        "provisional_passed": sum(c["passed"] and c["expected_provisional"] for c in results),
        "ranking": {
            "human_support_source": "synth-cases-r4.md §4",
            "baseline": {
                "projects": ["demo-p1", "demo-p2", "demo-p3", "demo-p4"],
                "bullets": "both per project",
                "skills": "all approved",
                "supported": baseline_supported,
                "denominator": all_labels,
            },
            "deterministic": {"supported": ranked_supported, "denominator": all_labels},
            "unknown_requirements": "Blocked JDs have no requirement gold; not invented",
        },
        "model_ranking": "not run",
        "cache": "pre-filled offline cache; no cold-download run",
        "cases": results,
    }
    directory = Path(report_dir or REPO / ".local/reports")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "m3.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    lines = [
        "# M3 frozen pack evaluation",
        "",
        (
            f"Normal: {report['normal_passed']}/6; provisional: {report['provisional_passed']}/2; "
            f"built: {report['built']}/8. Failures remain in the denominator."
        ),
        "",
        "| Case | Built | Pages | Overfull | Traced | Skills approved | Provisional | Pass |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in results:
        c = row.get("checks", {})
        lines.append(
            f"| {row['case']} | {row['built']} | {c.get('pages', 'failed')} | "
            f"{c.get('overfull', 'failed')} | {c.get('traced_bullets', 0)}/"
            f"{c.get('bullet_count', '?')} | {c.get('approved_skills', False)} | "
            f"{c.get('provisional', 'failed')} | {row['passed']} |"
        )
    lines.extend(
        [
            "",
            (
                f"Human-labelled requirement coverage: deterministic {ranked_supported}/"
                f"{all_labels}; fixed p1–p4 baseline {baseline_supported}/{all_labels}."
            ),
            "Baseline includes both bullets per project and all approved demo skills.",
            "Blocked JDs have unknown requirements and do not invent ranking labels.",
            "Model ranking: **not run**. Cache pre-filled; individual build times in JSON.",
            "",
        ]
    )
    (directory / "m3.md").write_text("\n".join(lines), encoding="utf8")
    return report


def main():
    with closing(connect(REPO / ".local/m3-eval.sqlite")) as db, run(db, "pack_eval") as counts:
        report = evaluate(db)
        counts["evaluated"] = report["denominator"]
        print(
            json.dumps(
                {
                    k: report[k]
                    for k in (
                        "denominator",
                        "built",
                        "normal_passed",
                        "provisional_passed",
                        "model_ranking",
                    )
                }
            )
        )


if __name__ == "__main__":
    main()
