"""The Citation Checker's rules on 10 planted errors and 10 correct controls against real records
(evals/planted_claims.json, frozen from the snapshot and SEC's archive). Offline: the model pass is off."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("planted_claims", ROOT / "evals" / "planted_claims.py")
planted_claims = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planted_claims)


async def test_rules_catch_dates_quotes_and_overreach_without_false_positives(monkeypatch):
    from ghost import pipeline
    monkeypatch.setattr(pipeline, "run_checker", pipeline.run_checker)  # restored after the eval swaps it out
    result = await planted_claims.score(use_model=False)
    by_error = {}
    for row in result["rows"]:
        if row["kind"] == "planted":
            by_error.setdefault(row["error"], []).append(row["caught"])
    assert by_error["wrong date"] == [True] * 3
    assert by_error["misquote"] == [True] * 3
    assert by_error["overreach"] == [True] * 3
    assert by_error["wrong status and reason"] == [False]  # left to the model pass
    assert result["caught"] == 9 and result["false_positives"] == 0 and result["model_pass"] is False
