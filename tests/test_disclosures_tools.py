"""The disclosures lane's tools always hand the researcher something citable, so a report never says
"the filings table has zero rows". Offline: reads the committed snapshot, and any network call fails."""

import json

import pytest
from agents.tool_context import ToolContext

from ghost import db, http, tools
from ghost.state import RunState


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("tests must not call the network")
    monkeypatch.setattr(http, "get", refuse)


def snapshot_one(sql: str) -> str:
    rows = db.run_select(sql).get("rows")
    assert rows, sql
    return next(iter(rows[0].values()))


async def invoke(tool, state: RunState, **args) -> dict:
    ctx = ToolContext(context=state, tool_name=tool.name, tool_call_id="t1", tool_arguments=json.dumps(args))
    return json.loads(await tool.on_invoke_tool(ctx, json.dumps(args)))


def test_filings_for_a_trial_with_8ks_are_citable():
    state = RunState("q")
    result = tools.trial_filings(state, "NCT05065411")  # Veru, the s1 sample
    assert result["cik"] == "0000863894" and result["filings"]
    for filing in result["filings"]:
        assert filing["evidence_id"] == f"sec:{filing['accession']}" and filing["evidence_id"] in state.store
        assert filing["relevance"] in ("nct_id", "drug_and_stop", "drug_and_condition", "drug_only")
    assert result["cik_evidence_id"] == "cik:0000863894" and "cik:0000863894" in state.store


def test_no_8k_is_a_citable_record_with_dates_and_cik():
    nct = snapshot_one("""SELECT t.nct_id FROM trials t JOIN trial_derived d USING (nct_id) JOIN sponsor_cik s USING (sponsor)
                          WHERE d.stopped AND s.files_8k AND t.nct_id NOT IN (SELECT nct_id FROM filings) ORDER BY 1 LIMIT 1""")
    state = RunState("q")
    result = tools.trial_filings(state, nct)
    record = state.store.get(result["evidence_id"])
    assert result["filings"] == [] and result["evidence_id"].startswith("sec:none:")
    assert record.title.startswith("No 8-K found from ") and f"for CIK {result['cik']}" in record.title
    assert record.data["found"] == 0 and record.data["windows"]
    assert record.source_url.startswith("https://www.sec.gov/edgar/search/")
    assert "zero rows" not in json.dumps(result)


def test_foreign_issuer_says_it_reports_on_6k():
    nct = snapshot_one("""SELECT t.nct_id FROM trials t JOIN trial_derived d USING (nct_id) JOIN sponsor_cik s USING (sponsor)
                          WHERE d.stopped AND s.files_8k = false AND t.nct_id NOT IN (SELECT nct_id FROM filings) ORDER BY 1 LIMIT 1""")
    state = RunState("q")
    result = tools.trial_filings(state, nct)
    assert "reports on 6-K" in state.store.get(result["evidence_id"]).title


def test_sponsor_without_an_sec_filer_is_a_citable_record():
    nct = snapshot_one("""SELECT t.nct_id FROM trials t JOIN trial_derived d USING (nct_id) LEFT JOIN sponsor_cik s USING (sponsor)
                          WHERE d.stopped AND s.sponsor IS NULL ORDER BY 1 LIMIT 1""")
    state = RunState("q")
    result = tools.trial_filings(state, nct)
    record = state.store.get(result["evidence_id"])
    assert result["evidence_id"].startswith("cik:none:") and record.title == f"No SEC filer found for {result['sponsor']}"


async def test_empty_edgar_search_names_dates_and_cik(monkeypatch):
    monkeypatch.setattr(http, "get", lambda *a, **k: {"hits": {"hits": [], "total": {"value": 0}}})
    state = RunState("q")
    result = await invoke(tools.search_sec_filings, state, query='"NCT05065411"', cik="863894",
                          start_date="2023-06-21", end_date="2024-06-25")
    title = state.store.get(result["evidence_id"]).title
    assert title == 'No 8-K found from 2023-06-21 to 2024-06-25 for CIK 0000863894 matching "NCT05065411"'


async def test_unmatched_sponsor_returns_no_sec_filer(monkeypatch):
    def fake_get(url, params=None, **kwargs):
        if url == tools.TICKERS:
            return {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
        return {"hits": {"hits": []}}  # EDGAR name search: nothing
    monkeypatch.setattr(http, "get", fake_get)
    state = RunState("q")
    result = await invoke(tools.find_sponsor_cik, state, sponsor_name="Nowhere Biotherapeutics GmbH")
    assert result["matches"] == [] and state.store.get(result["evidence_id"]).title == "No SEC filer found for Nowhere Biotherapeutics GmbH"


def test_excerpts_decode_entities_exactly():
    paragraphs = tools._paragraphs("<p>Veru&#8217;s ENABLAR-2 trial will proceed &#8220;subject to the availability of funding&#8221;.</p>")
    assert paragraphs == ["Veru’s ENABLAR-2 trial will proceed “subject to the availability of funding”."]
