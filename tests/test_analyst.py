"""Ask the ledger: the analyst agent writes SQL; the app reruns that SQL itself and checks the answer's numbers."""

import asyncio

import pytest
from fastapi.testclient import TestClient

import app as web
from ghost import analyst
from ghost.analyst import AnalystAnswer, no_dashes, unverified_numbers
from tests.conftest import live

COUNT_SQL = "SELECT why_stopped_category AS reason, count(*) AS n FROM trial_derived WHERE stopped GROUP BY 1 ORDER BY n DESC"


def stub(monkeypatch, out: AnalystAnswer):
    async def run(state):
        state.record_call("analyst", "query_trials_sql", {"sql": out.sql}, "6 rows")
        return out

    monkeypatch.setattr(analyst, "run_analyst", run)


def test_numbers_are_checked_against_the_table():
    rows = [{"reason": "safety", "n": 2905, "pct": 26.1}]
    assert unverified_numbers("2,905 trials, 26.1% of them, about 26%.", rows, "SELECT 1") == []
    assert unverified_numbers("COVID-19 and Covid19 led with 2905.", rows, "") == []
    assert unverified_numbers("At least 5 stopped trials in 2015.", rows, "HAVING count(*) >= 5") == []
    assert unverified_numbers("A total of 3,500 trials.", rows, "") == ["3,500"]


def test_dashes_are_removed():
    assert no_dashes("from 17–19 per year — a rise") == "from 17 to 19 per year, a rise"


def test_table_comes_from_rerunning_the_sql(monkeypatch):
    stub(monkeypatch, AnalystAnswer(sql=COUNT_SQL, answer="Most stopped trials gave a business reason.", chart="bar",
                                    label_column="reason", value_column="n"))
    r = asyncio.run(analyst.ask("Why do trials stop?"))
    assert r["ok"] and r["columns"] == ["reason", "n"] and len(r["rows"]) == 6
    assert r["chart"] == "bar" and r["unverified"] == []
    assert all(c["agent"] == "analyst" for c in r["tool_calls"])


def test_invented_number_is_flagged(monkeypatch):
    stub(monkeypatch, AnalystAnswer(sql=COUNT_SQL, answer="Exactly 99999 trials stopped."))
    assert asyncio.run(analyst.ask("How many stopped?"))["unverified"] == ["99999"]


def test_non_select_sql_is_not_run(monkeypatch):
    stub(monkeypatch, AnalystAnswer(sql="DELETE FROM trials", answer="Done."))
    r = asyncio.run(analyst.ask("Clean up the data"))
    assert not r["ok"] and r["rows"] == [] and "Rejected" in r["sql_error"]


def test_bar_chart_needs_numbers(monkeypatch):
    stub(monkeypatch, AnalystAnswer(sql="SELECT nct_id, sponsor FROM trials LIMIT 3", answer="Three trials.", chart="bar",
                                    label_column="nct_id", value_column="sponsor"))
    assert asyncio.run(analyst.ask("Show three trials"))["chart"] == "none"


def test_out_of_scope_has_no_table(monkeypatch):
    stub(monkeypatch, AnalystAnswer(sql="", answer="I can't give medical advice. I can count trials of a drug instead."))
    r = asyncio.run(analyst.ask("Is drug X safe for me?"))
    assert r["ok"] and r["rows"] == [] and not r["unverified"]


def test_empty_and_long_questions():
    assert not asyncio.run(analyst.ask("  "))["ok"]
    assert not asyncio.run(analyst.ask("x" * (analyst.MAX_QUESTION_CHARS + 1)))["ok"]


def test_timeout_is_an_answer_not_an_error(monkeypatch):
    async def slow(state):
        await asyncio.sleep(5)

    monkeypatch.setattr(analyst, "run_analyst", slow)
    monkeypatch.setattr(analyst, "ANALYST_TIMEOUT_S", 0.1)
    r = asyncio.run(analyst.ask("Anything"))
    assert not r["ok"] and "too long" in r["answer"]


def test_endpoint(monkeypatch):
    stub(monkeypatch, AnalystAnswer(sql=COUNT_SQL, answer="Six reasons."))
    body = TestClient(web.app).post("/api/ask", json={"question": "Why do trials stop?"}).json()
    assert body["ok"] and body["rows"] and body["sql"] == COUNT_SQL


def test_schema_is_in_the_prompt():
    assert "why_stopped_category" in analyst.analyst.instructions and "safety" in analyst.analyst.instructions


@live
def test_analyst_live():
    r = asyncio.run(analyst.ask("How many stopped trials gave each why_stopped_category?"))
    assert r["ok"] and r["rows"] and r["sql"].lower().lstrip().startswith(("select", "with"))
