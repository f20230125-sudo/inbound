import json
from pathlib import Path

from inbound.pause import check
from inbound.triage.rules import triage_messages
from inbound.triage.taxonomy import CATEGORIES


def metrics(gold, predicted):
    matrix = {a: dict.fromkeys(CATEGORIES, 0) for a in CATEGORIES}
    for actual, prediction in zip(gold, predicted, strict=True):
        matrix[actual][prediction] += 1
    per_category = {}
    for category in CATEGORIES:
        tp = matrix[category][category]
        support = sum(matrix[category].values())
        predictions = sum(row[category] for row in matrix.values())
        precision = tp / predictions if predictions else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_category[category] = {
            "support": support,
            "predicted": predictions,
            "true_positive": tp,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return {
        "denominator": len(gold),
        "confusion_matrix": matrix,
        "per_category": per_category,
        "macro_f1": sum(r["f1"] for r in per_category.values()) / len(CATEGORIES),
        "ps_call_recall": per_category["ps_call"]["recall"],
        "ps_admin_recall": per_category["ps_admin"]["recall"],
        "macro_f1_denominator": len(CATEGORIES),
        "zero_support": "precision/recall/F1 = 0",
    }


def baseline(db, output_dir, cases_path=None):
    check(db)
    cases_path = cases_path or Path(__file__).resolve().parents[1] / "synth/cases.json"
    definitions = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    # Filter before querying predictions. Held-out and attacks never enter scoring.
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
    triage_messages(db, set(selected))
    predictions = [
        db.execute("SELECT category FROM triage WHERE message_id=?", (identity,)).fetchone()[0]
        for identity in selected
    ]
    report = metrics([c["gold"]["category"] for c in dev], predictions)
    report.update(
        dataset=definitions["dataset"],
        split="dev",
        message_ids=[c["id"] for c in dev],
        clock=definitions["clock"],
        model_comparison="not run",
        urgency="pending M2 deadline extraction",
        ps_admin_deadline_recall="pending M2",
        corrections="Original rule predictions scored; corrections excluded",
        held_out="not scored",
        adversarial="not scored in this dev baseline",
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "m1.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        "# M1 dev triage baseline",
        "",
        f"Dataset: {report['dataset']}; dev only; n={len(dev)}.",
        "Held-out and adversarial splits: not scored. Model comparison: not run.",
        "Urgency and admin deadline recall: pending M2 extraction.",
        "Original predictions only; corrections excluded. Zero-support metrics = 0.",
        "",
        f"Macro-F1 ({len(CATEGORIES)} categories): {report['macro_f1']:.6f}",
        f"ps_call recall: {report['ps_call_recall']:.6f}",
        f"ps_admin recall: {report['ps_admin_recall']:.6f}",
        "",
        "| Category | Gold n | Predicted n | TP | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for c, row in report["per_category"].items():
        lines.append(
            f"| {c} | {row['support']} | {row['predicted']} | {row['true_positive']} | "
            f"{row['precision']:.6f} | {row['recall']:.6f} | {row['f1']:.6f} |"
        )
    lines += [
        "",
        "Confusion matrix: rows = gold; columns = predicted; counts (not percentages).",
        "",
        "| Gold / predicted | " + " | ".join(CATEGORIES) + " | Denominator |",
        "|---|" + "---:|" * (len(CATEGORIES) + 1),
    ]
    for category, row in report["confusion_matrix"].items():
        lines.append(
            "| "
            + category
            + " | "
            + " | ".join(str(row[c]) for c in CATEGORIES)
            + f" | {sum(row.values())} |"
        )
    (output_dir / "m1.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    from inbound.__main__ import main

    raise SystemExit(main(["baseline"]))
