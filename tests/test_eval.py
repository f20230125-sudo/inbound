from eval.run_eval import evaluate


def test_reproducible(tmp_path):
    first = evaluate(tmp_path / "one")
    second = evaluate(tmp_path / "two")
    first.pop("timings")
    second.pop("timings")
    assert first == second
    assert first["dev"]["triage"]["denominator"] == 64
    assert first["held-out"]["triage"]["denominator"] == 116
    assert first["packs"]["denominator"] == 8
    assert first["safety"]["forbidden_action_attempts"] == 0
    assert first["model_comparison"] == "not run"
