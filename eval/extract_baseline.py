"""Dev-only extraction metrics. The sole gold authority is synth/cases.json."""

import json
from contextlib import closing
from datetime import datetime
from pathlib import Path

from inbound.extract.pipeline import extract_messages
from inbound.pause import check


def rate(correct, denominator):
    return {
        "correct": correct,
        "denominator": denominator,
        "accuracy": correct / denominator if denominator else None,
    }


def equal(gold, prediction):
    if prediction is None or gold["status"] != prediction["status"]:
        return False
    if gold["normalized"] != prediction["normalized"]:
        return False
    if not prediction.get("_quote_valid", True):
        return False
    if gold["status"] == "unknown":
        return (not gold.get("missing_reason") or bool(prediction.get("missing_reason"))) and (
            not gold.get("source_text") or gold["source_text"] == prediction.get("source_text")
        )
    if gold["status"] == "conflicting":
        actual = prediction.get("candidates", [])
        expected = gold.get("candidates", [])
        return (
            len(actual) == len(expected)
            and {json.dumps(c["normalized"], sort_keys=True) for c in actual}
            == {json.dumps(c["normalized"], sort_keys=True) for c in expected}
            and all(c.get("source_text") and c.get("provenance") for c in actual)
        )
    if gold["status"] == "inferred" and (
        gold.get("anchor") != prediction.get("anchor") or gold["raw"] != prediction["raw"]
    ):
        return False
    for key in ("precision", "past_at_receipt", "observations", "components"):
        if key == "components":
            expected = gold.get(key)
            actual = prediction.get(key)
            if expected and (
                not actual
                or any(
                    expected[n]["normalized"] != actual[n]["normalized"]
                    or expected[n]["status"] != actual[n]["status"]
                    for n in expected
                )
            ):
                return False
        elif key in gold and gold[key] != prediction.get(key):
            return False
    origin = gold.get("provenance", {})
    actual_origin = prediction.get("provenance", {})
    if any(
        origin.get(k) != actual_origin.get(k)
        for k in ("message_id", "source", "name")
        if k in origin
    ):
        return False
    # Quote validation against source bytes is performed by baseline before scoring.
    return bool(prediction.get("_quote_valid", True))


def metrics(gold, predicted):
    per_field = {}
    full = correct = populated_correct = populated_n = abstentions = silent = deadline_correct = 0
    deadline_n = 0
    titles_correct = titles_n = requirements_correct = requirements_n = 0
    failures = []
    for index, (expected, actual) in enumerate(zip(gold, predicted, strict=True)):
        record_correct = True
        for name, value in expected.items():
            prediction = actual.get(name)
            ok = equal(value, prediction)
            if not ok:
                failures.append({"record": index, "field": name})
            record_correct &= ok
            correct += ok
            counts = per_field.setdefault(
                name,
                {
                    "correct": 0,
                    "denominator": 0,
                    "populated_correct": 0,
                    "populated_denominator": 0,
                    "abstentions": 0,
                },
            )
            counts["denominator"] += 1
            counts["correct"] += ok
            populated = value["status"] in {"found", "inferred"}
            if populated:
                populated_n += 1
                populated_correct += ok
                counts["populated_denominator"] += 1
                counts["populated_correct"] += ok
            abstain = bool(prediction and prediction["status"] in {"unknown", "conflicting"})
            counts["abstentions"] += abstain
            abstentions += abstain
            if name in {"deadline", "admin_deadline"}:
                deadline_n += 1
                deadline_correct += ok
                if (
                    prediction
                    and prediction["status"] in {"found", "inferred"}
                    and prediction["normalized"] is not None
                    and prediction["normalized"] != value["normalized"]
                    and not actual.get("_blocked", False)
                ):
                    silent += 1
            if name == "roles" and value["normalized"]:
                predicted_roles = prediction.get("normalized") or [] if prediction else []
                for i, role in enumerate(value["normalized"]):
                    titles_n += 1
                    chosen = predicted_roles[i] if i < len(predicted_roles) else {}
                    titles_correct += role["title"] == chosen.get("title")
                    if role["requirements"] is not None:
                        for j, requirement in enumerate(role["requirements"]):
                            requirements_n += 1
                            requirements = chosen.get("requirements") or []
                            requirements_correct += (
                                chosen.get("title") == role["title"]
                                and j < len(requirements)
                                and requirements[j]["text"] == requirement["text"]
                            )
        full += record_correct
    n = sum(len(record) for record in gold)
    for row in per_field.values():
        row["accuracy"] = row["correct"] / row["denominator"]
        row["populated_accuracy"] = (
            row["populated_correct"] / row["populated_denominator"]
            if row["populated_denominator"]
            else None
        )
    return {
        "applicable": rate(correct, n),
        "populated": rate(populated_correct, populated_n),
        "full_record": rate(full, len(gold)),
        "abstentions": abstentions,
        "deadline_exact_match": rate(deadline_correct, deadline_n),
        "silently_wrong_deadlines": silent,
        "per_field": per_field,
        "role_title": rate(titles_correct, titles_n),
        "requirement_association": rate(requirements_correct, requirements_n),
        "failures": failures,
    }


def validate_quote(db, record):
    if record["status"] == "unknown":
        return True
    if record.get("observations"):
        return all(
            validate_quote(
                db,
                {
                    "status": "found",
                    "source_text": o["source_text"],
                    "provenance": {"message_id": o["message_id"], "source": "message"},
                },
            )
            for o in record["observations"]
        )
    if record["status"] == "conflicting":
        return all(validate_quote(db, c) for c in record["candidates"])
    origin = record.get("provenance", {})
    message = db.execute(
        "SELECT * FROM messages WHERE provider='mail' AND provider_id=? AND source='synthetic'",
        (origin.get("message_id"),),
    ).fetchone()
    if message is None:
        return False
    if origin.get("source") == "attachment":
        row = db.execute(
            "SELECT text FROM attachments WHERE message_id=? AND filename=?",
            (message["id"], origin.get("name")),
        ).fetchone()
        source = row[0] if row else ""
    else:
        source = message["subject"] + "\n" + message["body_text"]
    return record["source_text"] in (source or "")


def baseline(db, output_dir, cases_path=None):
    check(db)
    cases_path = cases_path or Path(__file__).resolve().parents[1] / "synth/cases.json"
    definitions = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    dev = [c for c in definitions["cases"] if c["split"] == "dev"]
    selected = []
    for case in dev:
        row = db.execute(
            "SELECT id FROM messages WHERE provider='mail' AND provider_id=? "
            "AND source='synthetic'",
            (case["id"],),
        ).fetchone()
        if row is None:
            raise ValueError("Dev fixture missing from synthetic import")
        selected.append(row["id"])
    clock = datetime.fromisoformat(definitions["clock"])
    extract_messages(db, ids=set(selected), clock=lambda: clock)
    gold, predicted, ids = [], [], []
    for case, identity in zip(dev, selected, strict=True):
        if not case["gold"]["fields"]:
            continue
        local = db.execute(
            "SELECT fields_json FROM message_extractions WHERE message_id=?", (identity,)
        ).fetchone()
        revision = db.execute(
            "SELECT fields_json FROM opportunity_revisions WHERE message_id=?", (identity,)
        ).fetchone()
        fields = json.loads((revision or local)[0])
        for record in fields.values():
            record["_quote_valid"] = validate_quote(db, record)
        gold.append(case["gold"]["fields"])
        predicted.append(fields)
        ids.append(case["id"])
    report = metrics(gold, predicted)
    report.update(
        dataset=definitions["dataset"],
        denominator=len(dev),
        applicable_records=len(gold),
        message_ids=[c["id"] for c in dev],
        scored_record_ids=ids,
        clock=definitions["clock"],
        split="dev",
        held_out="not scored",
        adversarial="not scored in dev baseline",
        model_comparison="not run",
        correctness="Exact normalized/status, provenance origin and supported quote; "
        "inferred raw/anchor and precision checked; unknowns explicit",
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "m2.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf8"
    )
    lines = [
        "# M2 extraction baseline",
        "",
        f"Dev only: {len(dev)} messages; {len(gold)} applicable records.",
        "Held-out and adversarial: not scored. Model comparison: not run.",
        "",
        "| Metric | Correct | Denominator | Accuracy |",
        "|---|---:|---:|---:|",
    ]
    for name in (
        "applicable",
        "populated",
        "full_record",
        "deadline_exact_match",
        "role_title",
        "requirement_association",
    ):
        r = report[name]
        lines.append(f"| {name} | {r['correct']} | {r['denominator']} | {r['accuracy']} |")
    lines += [
        "",
        f"Abstentions (unknown/conflicting predictions): {report['abstentions']}",
        f"Silently wrong deadlines: {report['silently_wrong_deadlines']}",
        "",
        "| Field | Correct | Applicable | Populated correct | Populated | Abstentions |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, r in report["per_field"].items():
        lines.append(
            f"| {name} | {r['correct']} | {r['denominator']} | {r['populated_correct']} | "
            f"{r['populated_denominator']} | {r['abstentions']} |"
        )
    (output / "m2.md").write_text("\n".join(lines) + "\n", encoding="utf8")
    return report


if __name__ == "__main__":
    from inbound.db import connect
    from inbound.ledger import run
    from inbound.settings import Settings

    settings = Settings.from_env()
    with closing(connect(settings.db_path)) as db, run(db, "extract_baseline") as counts:
        report = baseline(db, settings.report_dir)
        counts["evaluated"] = report["denominator"]
        print(
            json.dumps(
                {
                    k: report[k]
                    for k in ("split", "denominator", "applicable", "silently_wrong_deadlines")
                }
            )
        )
