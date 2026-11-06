"""find_discrepancies: the discrepancy finder as a tool. Hand-checked rows come first, every row is citable, the
count is citable, and an empty search is a citable record. Offline: reads the committed snapshot."""

import json

import pytest
from agents.tool_context import ToolContext

from ghost import db, http, tools
from ghost.citecheck import check_claim
from ghost.state import RunState


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("tests must not call the network")
    monkeypatch.setattr(http, "get", refuse)


def test_hand_checked_rows_come_first_and_are_citable():
    state = RunState("q")
    result = tools.discrepancy_rows(state)
    hand = db.run_select("SELECT count(DISTINCT nct_id) AS n FROM discrepancies WHERE label = 'discrepancy' AND decided_by = 'hand_checked'")
    assert result["hand_checked_trials"] == hand["rows"][0]["n"] > 0
    deciders = [t["decided_by"] for t in result["trials"]]
    assert deciders == sorted(deciders, key=lambda d: d != "hand_checked"), "hand-checked rows first"
    assert len({t["nct_id"] for t in result["trials"]}) == len(result["trials"]), "one row per trial"
    for trial in result["trials"]:
        assert trial["label"] == "discrepancy"
        assert trial["registry_evidence_id"] == f"ctgov:{trial['nct_id']}" and trial["registry_evidence_id"] in state.store
        assert trial["sec_evidence_id"] == f"sec:{trial['accession']}" and trial["sec_evidence_id"] in state.store
    assert result["summary_evidence_id"] in state.store
    assert "not proof of intent" in result["note"]


def test_vtv_quote_passes_the_citation_rules():
    """The sample's 8-K quote, as the tool stores it, supports a claim that quotes it."""
    state = RunState("q")
    trial = tools.discrepancy_rows(state, nct_id="nct03980730")["trials"][0]
    assert (trial["decided_by"], trial["registry_reason"], trial["accession"]) == ("hand_checked", "for business reasons", "0001564590-21-008154")
    claim = 'vTv\'s 8-K filed on 2021-02-24 says "the phase 2 Elevage Study of azeliragon did not meet its primary objective".'
    records = [state.store.get(trial["sec_evidence_id"]).__dict__]
    assert check_claim(claim, records) == []


def test_filters_and_sql_quoting():
    state = RunState("q")
    alz = tools.discrepancy_rows(state, condition="alzheimer")
    assert alz["trials"] and all(t["nct_id"] for t in alz["trials"])
    assert "condition alzheimer" in alz["summary"]
    odd = tools.discrepancy_rows(state, sponsor="O'Brien Pharma")  # a quote in the name must not break the SQL
    assert "error" not in odd and odd["trials"] == []
    assert odd["summary_evidence_id"] in state.store and "0 trials" in odd["summary"]
    assert "Do not write that a table is empty" in odd["note"]


def test_unknown_labels_fall_back_and_limit_is_capped():
    state = RunState("q")
    result = tools.discrepancy_rows(state, labels=["drop table"], limit=500)
    assert all(t["label"] == "discrepancy" for t in result["trials"])
    assert len(result["trials"]) <= 20


async def test_tool_is_wired_for_the_lead_and_disclosures_lane():
    assert tools.find_discrepancies in tools.LEAD_TOOLS and tools.find_discrepancies in tools.DISCLOSURES_TOOLS
    state = RunState("q")
    args = {"sponsor": "vTv", "labels": ["discrepancy"]}
    ctx = ToolContext(context=state, tool_name="find_discrepancies", tool_call_id="t1", tool_arguments=json.dumps(args))
    result = json.loads(await tools.find_discrepancies.on_invoke_tool(ctx, json.dumps(args)))
    assert [t["nct_id"] for t in result["trials"]] == ["NCT03980730"]


def test_sql_rows_from_discrepancies_keep_their_filing_link():
    """query_trials_sql over the discrepancies table registers each 8-K with its link, not a blank source."""
    state = RunState("q")
    sql = "SELECT nct_id, sponsor, accession, filed_date, filing_url, sec_quote FROM discrepancies WHERE nct_id = 'NCT03980730' AND label = 'discrepancy'"
    rows = db.run_select(sql)["rows"]
    ids = tools._register_rows(state, sql, rows)
    record = state.store.get("sec:0001564590-21-008154")
    assert "sec:0001564590-21-008154" in ids
    assert record.source_url.startswith("https://www.sec.gov/Archives/") and record.title == "vTv Therapeutics 8-K filed 2021-02-24"


@pytest.mark.parametrize("sql", [
    "SELECT * FROM discrepancies LIMIT 5",
    "select t.nct_id from trials t join main.discrepancies d using (nct_id)",
    'SELECT count(*) FROM "Discrepancies"',
    "select * from trials, discrepancies",
])
async def test_sql_on_discrepancies_points_to_the_tool(sql):
    """The SQL tool refuses the discrepancies table, so every comparison goes through find_discrepancies."""
    state = RunState("q")
    args = {"sql": sql}
    ctx = ToolContext(context=state, tool_name="query_trials_sql", tool_call_id="t1", tool_arguments=json.dumps(args))
    result = json.loads(await tools.query_trials_sql.on_invoke_tool(ctx, json.dumps(args)))
    assert "find_discrepancies" in result["error"]
    assert not state.store.records, "a refused query registers no evidence"


async def test_sql_that_only_names_the_table_in_a_string_still_runs():
    state = RunState("q")
    args = {"sql": "SELECT row_count FROM snapshot_meta WHERE table_name = 'discrepancies'"}
    ctx = ToolContext(context=state, tool_name="query_trials_sql", tool_call_id="t1", tool_arguments=json.dumps(args))
    result = json.loads(await tools.query_trials_sql.on_invoke_tool(ctx, json.dumps(args)))
    assert "error" not in result and result["rows"][0]["row_count"] > 0
