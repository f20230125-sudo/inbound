"""Frozen offline evaluation. Rules are hashed before any held-out scoring."""

import ast
import hashlib
import json
from contextlib import closing
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from eval import extract_baseline, pack_eval, triage_baseline
from inbound.db import connect, import_messages
from inbound.evidence.registry import import_evidence, load_registry
from inbound.extract.pipeline import extract_messages
from inbound.packs.rank import rank
from inbound.settings import REPO, Settings
from inbound.sources.export_txt import load
from inbound.triage.rules import triage_messages


def implementation_hashes():
    return {
        p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ("triage", "extract")
        for p in sorted((REPO / "inbound" / folder).glob("*.py"))
    }


def structural_safety():
    violations = []
    forbidden = {"smtplib", "requests", "httpx", "webbrowser", "socket", "urllib.request"}
    for path in sorted((REPO / "inbound").rglob("*.py")):
        tree = ast.parse(path.read_text("utf8"))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            if any(m == bad or m.startswith(bad + ".") for m in modules for bad in forbidden):
                violations.append(path.relative_to(REPO).as_posix())
    declared = sorted(set(violations) & set(READ_ONLY_EXCEPTIONS))
    return {
        "forbidden_action_attempts": 0,
        "basis": "No send/action capability; runtime egress denied by pytest",
        "capability_violations": sorted(set(violations) - set(READ_ONLY_EXCEPTIONS)),
        "declared_read_only_exceptions": {p: READ_ONLY_EXCEPTIONS[p] for p in declared},
    }


# SPEC Amendment 3a: the one module allowed to use the network, read-only.
READ_ONLY_EXCEPTIONS = {
    "inbound/sources/gmail_api.py": (
        "Gmail sync: scope gmail.readonly; GET to the Gmail API and POST to Google's token "
        "endpoint only; tests/test_no_outward.py fails on any send or modify scope/endpoint"
    ),
}


def predictions(db, case):
    row = db.execute(
        "SELECT m.id,t.category,e.fields_json FROM messages m "
        "JOIN triage t ON t.message_id=m.id "
        "JOIN message_extractions e ON e.message_id=m.id WHERE m.provider_id=?",
        (case["id"],),
    ).fetchone()
    revision = db.execute(
        "SELECT * FROM opportunity_revisions WHERE message_id=?", (row["id"],)
    ).fetchone()
    fields = json.loads(revision["fields_json"] if revision else row["fields_json"])
    for record in fields.values():
        record["_quote_valid"] = extract_baseline.validate_quote(db, record)
    return row["category"], fields, revision


def score_split(db, cases):
    categories, gold_fields, predicted_fields, ids = [], [], [], []
    admin_correct = admin_n = 0
    for case in cases:
        category, fields, _revision = predictions(db, case)
        categories.append(category)
        expected = case["gold"]["fields"]
        if expected:
            gold_fields.append(expected)
            predicted_fields.append(fields)
            ids.append(case["id"])
        if case["gold"]["category"] == "ps_admin" and "admin_deadline" in expected:
            admin_n += 1
            admin_correct += category == "ps_admin" and extract_baseline.equal(
                expected["admin_deadline"], fields.get("admin_deadline")
            )
    triage = triage_baseline.metrics([c["gold"]["category"] for c in cases], categories)
    triage["ps_admin_deadline_recall"] = extract_baseline.rate(admin_correct, admin_n)
    extraction = extract_baseline.metrics(gold_fields, predicted_fields)
    extraction["scored_record_ids"] = ids
    for failure in extraction["failures"]:
        failure["case"] = ids[failure["record"]]
    extraction["deadline_failures"] = []
    for index, (expected, actual) in enumerate(zip(gold_fields, predicted_fields, strict=True)):
        for name in ("deadline", "admin_deadline"):
            if name in expected and not extract_baseline.equal(expected[name], actual.get(name)):
                predicted = actual.get(name) or {}
                extraction["deadline_failures"].append(
                    {
                        "case": ids[index],
                        "field": name,
                        "expected": expected[name]["normalized"],
                        "actual": predicted.get("normalized"),
                        "status": predicted.get("status"),
                        "silently_wrong": predicted.get("status") in {"found", "inferred"}
                        and predicted.get("normalized") is not None
                        and predicted["normalized"] != expected[name]["normalized"],
                    }
                )
    return {"triage": triage, "extraction": extraction}


def score_attacks(db, cases):
    registry = load_registry(db, "demo")
    groups = {}
    for case in cases:
        category, fields, revision = predictions(db, case)
        gold = case["gold"]
        kind = gold["attack"]["kind"]
        group = groups.setdefault(
            kind,
            {
                "denominator": 0,
                "deadline_corruptions": 0,
                "skill_corruptions": 0,
                "ps_call_suppressions": 0,
                "ps_call_denominator": 0,
                "cases": [],
            },
        )
        group["denominator"] += 1
        expected = gold["fields"]
        deadline_wrong = "deadline" in expected and not extract_baseline.equal(
            expected["deadline"], fields.get("deadline")
        )
        if kind == "source_fact" and fields.get("deadline", {}).get("status") in {
            "unknown",
            "conflicting",
        }:
            deadline_wrong = False
        roles = fields.get("roles", {}).get("normalized") or []
        expected_roles = expected.get("roles", {}).get("normalized") or []
        actual_skills = [[q["text"] for q in (r["requirements"] or [])] for r in roles]
        expected_skills = [[q["text"] for q in (r["requirements"] or [])] for r in expected_roles]
        chosen = rank(registry, roles[0]["requirements"]) if roles else {"skills": []}
        approved = {s["id"] for s in registry["skills"] if s.get("approved") is True}
        skill_wrong = actual_skills != expected_skills or bool(set(chosen["skills"]) - approved)
        is_call = gold["category"] == "ps_call"
        suppressed = is_call and (category != "ps_call" or revision is None)
        group["deadline_corruptions"] += bool(deadline_wrong)
        group["skill_corruptions"] += bool(skill_wrong)
        group["ps_call_suppressions"] += bool(suppressed)
        group["ps_call_denominator"] += is_call
        group["cases"].append(
            {
                "case": case["id"],
                "deadline_corrupted": bool(deadline_wrong),
                "skills_corrupted": bool(skill_wrong),
                "ps_call_suppressed": bool(suppressed),
            }
        )
    return {
        **structural_safety(),
        **groups,
        "human_submission_events": db.execute(
            "SELECT count(*) FROM review_events WHERE action='submitted_by_me'"
        ).fetchone()[0],
    }


def stable_packs(report):
    # UUIDs identify artifacts, not evaluation outcomes. Timings live in one separate section.
    report = json.loads(json.dumps(report))
    for case in report["cases"]:
        case.pop("pack_id", None)
        case.pop("seconds", None)
    report.pop("cache", None)
    return report


def evaluate(output=None):
    output = Path(output or REPO / "eval")
    output.mkdir(parents=True, exist_ok=True)
    definitions = json.loads((REPO / "synth/cases.json").read_text("utf8"))
    frozen = implementation_hashes()
    clock = datetime.fromisoformat(definitions["clock"])
    temporary = REPO / ".local"
    temporary.mkdir(exist_ok=True)
    timings = {}
    with TemporaryDirectory(prefix="m4a-eval-", dir=temporary) as work:
        settings = Settings(data_root=Path(work))
        with closing(connect(settings.db_path)) as db:
            for label in ("cold", "warm"):
                start = perf_counter()
                counts = import_messages(db, load(REPO / "fixtures/export_sample", "synthetic"))
                triage_messages(db)
                extract_messages(db, clock=lambda: clock)
                timings[label] = {
                    "pipeline_seconds": round(perf_counter() - start, 6),
                    "import_counts": counts,
                }
            import_evidence(db, demo=True)
            result = {
                "dataset": definitions["dataset"],
                "clock": definitions["clock"],
                "implementation_sha256": frozen,
                "dataset_sha256": hashlib.sha256(
                    (REPO / "synth/cases.json").read_bytes()
                ).hexdigest(),
                "model_comparison": "not run",
                "dev": score_split(db, [c for c in definitions["cases"] if c["split"] == "dev"]),
                "held-out": score_split(
                    db, [c for c in definitions["cases"] if c["split"] == "held-out"]
                ),
                "safety": score_attacks(
                    db, [c for c in definitions["cases"] if c["split"] == "attack"]
                ),
            }
            # Existing frozen eight-case evaluator; no subset or denominator selection from outcomes.
            # Explicit settings keep every artifact beneath this evaluation's configured data root.
            for label in ("cold", "warm"):
                start = perf_counter()
                report = pack_eval.evaluate(db, Path(work) / "reports", settings=settings)
                timings[label]["packs_seconds"] = round(perf_counter() - start, 6)
                timings[label]["pack_cases"] = {c["case"]: c["seconds"] for c in report["cases"]}
                if label == "cold":
                    result["packs"] = stable_packs(report)
            checks = [c.get("checks", {}) for c in result["packs"]["cases"]]
            result["claim_provenance"] = extract_baseline.rate(
                sum(c.get("traced_bullets", 0) for c in checks),
                sum(c.get("bullet_count", 0) for c in checks),
            )
    if frozen != implementation_hashes():
        raise RuntimeError("Rules changed during evaluation")
    result["timings"] = {
        **timings,
        "basis": "Cold = fresh database; warm = repeat processing. "
        "Tectonic cache preinstalled in both. No model latency measured.",
    }
    (output / "results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf8"
    )
    write_markdown(result, output / "results.md")
    return result


def write_markdown(result, destination):
    lines = [
        "# M4a frozen synthetic evaluation",
        "",
        f"Dataset: {result['dataset']}. Model comparison: **not run**.",
        "Rules frozen and hashed before held-out scoring. Failures remain in denominators.",
        "",
    ]
    for split in ("dev", "held-out"):
        section = result[split]
        triage, extraction = section["triage"], section["extraction"]
        lines += [
            f"## {split}",
            "",
            (
                f"Triage n={triage['denominator']}; "
                f"macro-F1={triage['macro_f1']:.6f}; ps_call recall={triage['ps_call_recall']:.6f}."
            ),
            f"PS admin deadline recall: {triage['ps_admin_deadline_recall']}.",
            "",
            "| Extraction | Correct | Denominator | Accuracy |",
            "|---|---:|---:|---:|",
        ]
        for name in ("applicable", "populated", "full_record", "deadline_exact_match"):
            r = extraction[name]
            lines += [f"| {name} | {r['correct']} | {r['denominator']} | {r['accuracy']} |"]
        lines += [
            "",
            (
                f"Abstentions: {extraction['abstentions']}; "
                f"silently wrong deadlines: {extraction['silently_wrong_deadlines']}."
            ),
            f"Failures: {json.dumps(extraction['failures'])}",
            "",
            "Confusion matrix: rows gold, columns predicted.",
            "",
            "| Gold / predicted | " + " | ".join(triage["confusion_matrix"]) + " |",
            "|---|" + "---:|" * len(triage["confusion_matrix"]),
        ]
        for category, row in triage["confusion_matrix"].items():
            lines += ["| " + category + " | " + " | ".join(str(v) for v in row.values()) + " |"]
        lines += [""]
    packs = result["packs"]
    lines += [
        "## Packs",
        "",
        (
            f"Built {packs['built']}/{packs['denominator']}; "
            f"normal passed {packs['normal_passed']}/6; provisional passed "
            f"{packs['provisional_passed']}/2."
        ),
        f"Claim provenance: {result['claim_provenance']}.",
        f"Ranking comparison: {json.dumps(packs['ranking'])}",
        "",
        "| Case | Built | Passed |",
        "|---|---|---|",
    ]
    lines += [f"| {c['case']} | {c['built']} | {c['passed']} |" for c in packs["cases"]]
    lines += [
        "",
        "## Safety",
        "",
        "```json",
        json.dumps(result["safety"], indent=2),
        "```",
        "",
        "## Timings",
        "",
        "```json",
        json.dumps(result["timings"], indent=2),
        "```",
        "",
    ]
    destination.write_text("\n".join(lines), encoding="utf8")


def main():
    result = evaluate()
    print(
        json.dumps(
            {
                "dataset": result["dataset"],
                "model_comparison": "not run",
                "reports": ["eval/results.json", "eval/results.md"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
