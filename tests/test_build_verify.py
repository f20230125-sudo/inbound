import json
import subprocess
from pathlib import Path

import pytest

from inbound.packs.build import TECTONIC, compile_tex, create_pack
from inbound.packs.verify import verify
from tests.m3_helpers import opportunity, snapshot


def test_demo_build_offline_and_trace(database):
    result = create_pack(database, opportunity(database), demo=True)
    checks = result["checks"]
    assert checks["passed"] and checks["pages"] == 1 and checks["overfull"] == 0
    assert checks["traced_bullets"] == checks["bullet_count"] > 0
    assert checks["approved_skills"] and checks["identity_line_check"]
    assert checks["metadata_check"] and checks["canary_check"]
    assert result["status"] == "needs_review"
    pdf = Path(result["files"]["pdf"])
    assert pdf.name.startswith("DEMO-2023-CS-0042-Sara-Qamar-")
    assert all(".invalid" in link for link in checks["links"])
    altered = snapshot()
    altered["projects"][0]["bullets"][0]["text_plain"] = "A claim absent from the PDF"
    failed = verify(pdf, pdf.parent / "build.log", altered, result["selection"], result["rendered"])
    assert not failed["passed"] and failed["traced_bullets"] < failed["bullet_count"]


def test_failed_build_leaves_no_success_record(database, monkeypatch):
    from inbound.packs import build

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(build, "compile_tex", fail)
    with pytest.raises(RuntimeError):
        create_pack(database, opportunity(database), demo=True)
    assert database.execute("SELECT status FROM packs").fetchone()[0] == "blocked"
    assert database.execute("SELECT status FROM runs WHERE kind='pack'").fetchone()[0] == "failed"


def test_subprocess_allowlist_is_exact(tmp_path):
    for command in (
        [str(TECTONIC)],
        ["cmd", "/c", str(TECTONIC)],
        [str(TECTONIC), "-X", "compile", "body.tex"],
    ):
        with pytest.raises(AssertionError):
            subprocess.run(command, check=False)
    with pytest.raises(AssertionError):
        subprocess.Popen("powershell")
    assert callable(compile_tex)


def test_pause_between_stages(database, monkeypatch):
    from inbound.packs import build
    from inbound.pause import PausedError, set_paused

    original = build.render

    def paused(*args, **kwargs):
        value = original(*args, **kwargs)
        set_paused(database, True)
        return value

    monkeypatch.setattr(build, "render", paused)
    with pytest.raises(PausedError):
        create_pack(database, opportunity(database), demo=True)
    assert not database.execute("SELECT 1 FROM packs WHERE status='needs_review'").fetchone()


def test_eight_frozen_cases(database):
    from eval.pack_eval import evaluate

    report = evaluate(database)
    assert report["denominator"] == 8
    assert report["normal_passed"] == 6 and report["provisional_passed"] == 2
    assert report["model_ranking"] == "not run"
    assert (
        report["ranking"]["deterministic"]["supported"]
        >= report["ranking"]["baseline"]["supported"]
    )
    assert all(c["checks"]["passed"] for c in report["cases"])
    assert json.loads(Path(".local/reports/m3.json").read_text())["denominator"] == 8


def test_call_naming_rule_and_canary_checks(database, tmp_path):
    from copy import deepcopy

    result = create_pack(database, opportunity(database, "P-D05"), demo=True)
    pdf = Path(result["files"]["pdf"])
    assert pdf.name.startswith("DEMO-2023-CS-0042_Sara-Qamar_")
    # Check canaries independently with a known phrase present in the actual PDF.
    contaminated = verify(
        pdf,
        pdf.parent / "build.log",
        snapshot(),
        result["selection"],
        result["rendered"],
        canaries=["Sara Qamar"],
    )
    assert not contaminated["passed"] and not contaminated["canary_check"]
    altered = deepcopy(result["rendered"])
    altered["filename"] = "Wrong.pdf"
    assert not verify(pdf, pdf.parent / "build.log", snapshot(), result["selection"], altered)[
        "filename_check"
    ]
    bad_log = tmp_path / "bad.log"
    bad_log.write_text("Overfull \\hbox")
    assert (
        verify(pdf, bad_log, snapshot(), result["selection"], result["rendered"])["overfull"] == 1
    )


@pytest.mark.parametrize("identity", ["J02", "J05", "J08"])
def test_attack_pack_has_no_added_skill_or_canary(database, identity):
    result = create_pack(database, opportunity(database, identity), demo=True)
    assert result["checks"]["passed"]
    directory = Path(result["files"]["pdf"]).parent
    content = "\n".join(
        path.read_text(encoding="utf8")
        for path in directory.iterdir()
        if path.suffix in {".tex", ".log", ".json", ".txt"}
    )
    assert "SYNTHETIC-CANARY" not in content
    assert "Kubernetes" not in (directory / "skills.tex").read_text()
    assert database.execute("SELECT status FROM packs").fetchone()[0] == "needs_review"


def test_timeout_and_nonzero_exit_are_failures(tmp_path, monkeypatch):
    from inbound.packs import build

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 120)

    monkeypatch.setattr(build.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="timeout"):
        compile_tex(tmp_path)
    (tmp_path / "body.pdf").write_bytes(b"stale")
    monkeypatch.setattr(
        build.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "failure")
    )
    with pytest.raises(RuntimeError, match="failed"):
        compile_tex(tmp_path)


def test_cli_evidence_and_demo_pack_with_safe_ledger(tmp_path, monkeypatch, capsys):
    from inbound.__main__ import main
    from inbound.db import connect
    from inbound.evidence import registry
    from inbound.pause import set_paused

    monkeypatch.setenv("INBOUND_DATA_ROOT", str(tmp_path))
    db = connect(tmp_path / "demo.sqlite")
    oid = opportunity(db)

    def frozen_import(connection):
        data = json.loads(Path("fixtures/evidence_snapshot.json").read_text(encoding="utf8"))
        registry.store_registry(connection, data)
        return data

    # CLI dispatch is exercised without opening the live CV or portfolio sources.
    original_import = registry.import_evidence
    monkeypatch.setattr(registry, "import_evidence", frozen_import)
    assert main(["evidence", "import"]) == 0
    assert json.loads(capsys.readouterr().out)["projects"] == 21
    # Demo loading uses its real fixture importer, separately from the public CLI stub.
    monkeypatch.setattr(registry, "import_evidence", original_import)
    assert main(["pack", str(oid), "--demo"]) == 0
    assert json.loads(capsys.readouterr().out)["checks"]["passed"]
    assert [(r["kind"], r["status"]) for r in db.execute("SELECT * FROM runs")] == [
        ("evidence", "success"),
        ("pack", "success"),
    ]
    set_paused(db, True)
    assert main(["pack", str(oid), "--demo"]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "PausedError"
    assert db.execute("SELECT count(*) FROM packs").fetchone()[0] == 1
    db.close()


def test_eval_failures_keep_denominator_and_independent_baseline(database, tmp_path, monkeypatch):
    from eval import pack_eval

    def fail(*args, **kwargs):
        raise RuntimeError("compiler unavailable")

    monkeypatch.setattr(pack_eval, "create_pack", fail)
    report = pack_eval.evaluate(database, report_dir=tmp_path)
    assert report["denominator"] == 8 and len(report["cases"]) == 8
    assert report["built"] == report["normal_passed"] == report["provisional_passed"] == 0
    assert report["ranking"]["baseline"]["supported"] == 18
    assert report["ranking"]["deterministic"]["denominator"] == 18
