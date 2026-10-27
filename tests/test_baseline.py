import json
from pathlib import Path

import pytest

from eval.triage_baseline import baseline, metrics
from inbound.db import import_messages
from inbound.sources.export_txt import load


def test_hand_computed_metrics():
    result = metrics(["ps_call", "ps_call", "ps_admin"], ["ps_call", "ps_admin", "ps_admin"])
    assert result["confusion_matrix"]["ps_call"]["ps_admin"] == 1
    assert result["per_category"]["ps_call"]["recall"] == 0.5
    assert result["per_category"]["ps_admin"]["precision"] == 0.5
    assert result["per_category"]["personal"]["support"] == 0
    assert result["per_category"]["personal"]["f1"] == 0
    assert result["macro_f1"] == pytest.approx((2 / 3 + 2 / 3) / 12)


def test_empty_metrics():
    result = metrics([], [])
    assert result["denominator"] == 0
    assert result["macro_f1"] == 0
    assert result["ps_call_recall"] == 0


def test_dev_only_and_corrections_separate(database, tmp_path):
    import_messages(database, load(Path("fixtures/export_sample"), "synthetic"))
    report = baseline(database, tmp_path)
    assert database.execute("SELECT count(*) FROM triage").fetchone()[0] == 64
    assert report["split"] == "dev"
    assert report["denominator"] == 64
    assert len(report["message_ids"]) == 64
    assert all(i.startswith(("P-D", "O-D")) for i in report["message_ids"])
    assert report["per_category"]["ps_call"]["support"] == 20
    assert report["per_category"]["ps_admin"]["support"] == 2
    database.execute("UPDATE triage SET corrected_category='personal'")
    database.commit()
    assert baseline(database, tmp_path)["confusion_matrix"] == report["confusion_matrix"]
    assert (
        database.execute(
            "SELECT count(*) FROM triage WHERE corrected_category='personal'"
        ).fetchone()[0]
        == 64
    )
    assert json.loads((tmp_path / "m1.json").read_text())["denominator"] == 64
    assert (tmp_path / "m1.md").is_file()
