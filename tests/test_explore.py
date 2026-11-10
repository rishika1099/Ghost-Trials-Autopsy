"""The Explore section: instant SQL views of the snapshot (ledger, sponsor report card, stories that differ)."""

from fastapi.testclient import TestClient

import app as web
from ghost import db, explore
from ghost.tools import STATS_SQL

client = TestClient(web.app)


def test_ledger_matches_the_agents_base_rates():
    """The page and get_snapshot_stats must never disagree on the same number."""
    head = explore.ledger()["headline"]
    stats = db.run_select(STATS_SQL)["rows"][0]
    assert head["trials"] == stats["trials"] and head["stopped"] == stats["stopped"]
    assert head["stopped"] - head["stopped_enrolled"] == stats["stopped_never_enrolled"]
    assert abs((100 - head["pct_stopped_posted"]) - stats["pct_stopped_no_results"]) < 0.2
    assert 0 < head["silent"] <= head["stopped_no_results"] <= head["stopped_enrolled"]
    assert head["silent_participants"] > 0


def test_ledger_breakdowns_add_up():
    data = explore.ledger()
    head = data["headline"]
    assert sum(r["stopped_enrolled"] for r in data["by_reason"]) == head["stopped_enrolled"]
    assert sum(r["silent"] for r in data["by_reason"]) == head["silent"]
    years = [r["year"] for r in data["by_year"]]
    assert years == sorted(years) and min(years) >= 2015 and max(years) <= 2023


def test_never_posted_sample_is_silent_on_its_sponsor_card():
    """README sample s2: Sorrento's COVI-MSC trial NCT04903327 has no posted results and no linked paper."""
    card = explore.sponsor_card("Sorrento")
    assert card["sponsor"] == "Sorrento Therapeutics, Inc."
    row = next(t for t in card["trials"] if t["nct_id"] == "NCT04903327")
    assert row["silent"] and not row["results_posted"] and not row["linked_pub"]
    assert card["sec"]["cik"] == "0000850261"


def test_sponsor_card_counts_hand_checked_discrepancies():
    card = explore.sponsor_card("vTv Therapeutics")
    assert card["differ"]["trials"] >= 1 and card["differ"]["named"] >= 1
    assert any(t["nct_id"] == "NCT03980730" and t["differs"] for t in card["trials"])


def test_rank_only_for_sponsors_with_enough_stopped_trials():
    small = explore.sponsor_card("Sorrento")
    assert small["headline"]["stopped_enrolled"] < explore.PEER_MIN_ENROLLED_STOPPED and small["rank"] is None
    big = explore.sponsor_card("Arrowhead")
    assert big["rank"]["peers"] == explore.leaderboard()["peers"]
    assert big["rank"]["share_more_silent"] + big["rank"]["share_less_silent"] <= 100


def test_leaderboard_respects_the_minimum():
    board = explore.leaderboard()
    for row in board["most_silent"] + board["least_silent"]:
        assert row["stopped_enrolled"] >= board["min_stopped"]
    assert board["most_silent"][0]["pct_silent"] >= board["least_silent"][0]["pct_silent"]


def test_differ_wall_puts_hand_checked_first():
    rows = explore.differ_wall()["trials"]
    kinds = [r["kind"] for r in rows]
    assert kinds == sorted(kinds, key=["hand_checked", "names_trial", "drug_lead"].index)
    hand = {r["nct_id"] for r in rows if r["kind"] == "hand_checked"}
    assert {"NCT03980730", "NCT05528861", "NCT02227784", "NCT02452528", "NCT04802837"} <= hand
    assert len({r["nct_id"] for r in rows}) == len(rows)  # one row per trial
    assert all(r["filing_url"].startswith("https://www.sec.gov/") for r in rows)


def test_endpoints():
    assert client.get("/api/ledger").json()["leaderboard"]["peers"] > 0
    assert client.get("/api/differ").json()["trials"]
    assert client.get("/api/sponsors", params={"q": "arrow"}).json()["sponsors"][0]["sponsor"].startswith("Arrowhead")
    assert client.get("/api/sponsors", params={"q": "a"}).json()["sponsors"] == []  # too short to search
    assert client.get("/api/sponsor", params={"name": "Arrowhead"}).json()["sponsor"] == "Arrowhead Pharmaceuticals"
    assert client.get("/api/sponsor", params={"name": "zzzz no such sponsor"}).status_code == 404


def test_sponsor_name_is_a_parameter_not_sql():
    """Names go to DuckDB as bound parameters, so quotes and SQL in them are just text."""
    for name in ["'; DROP TABLE trials; --", "O'Brien", "%", "_"]:
        response = client.get("/api/sponsor", params={"name": name})
        assert response.status_code in (200, 404)
    assert db.run_select("SELECT count(*) AS n FROM trials")["rows"][0]["n"] > 0


def test_page_has_the_explore_section():
    html = client.get("/").text
    for marker in ['id="explore"', "/api/ledger", "/api/differ", "/api/sponsor?name=", "Copy a link to this case"]:
        assert marker in html
