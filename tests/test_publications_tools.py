"""The publications lane only calls an article a trial's results paper when it is formally linked and came out
after the trial started. Reviews that merely name the NCT ID (europepmc_mention) are mentions, not publications.
Offline: reads the committed snapshot; live PubMed is stubbed."""

import pytest

from ghost import db, http, report, tools
from ghost.state import RunState

NEVER_POSTED = "NCT04903327"  # README "never posted" sample: only reviews name it
BACKGROUND = "NCT04541888"  # its only ctgov_result paper is from 2005, the trial started in 2020
LINKED = "NCT02190747"  # palovarotene phase 2, its results paper lists the NCT ID


@pytest.fixture(autouse=True)
def pubmed_finds_nothing(monkeypatch):
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append(url)
        if "esearch" in url:
            return {"esearchresult": {"idlist": []}}
        raise AssertionError(f"unexpected network call: {url}")

    monkeypatch.setattr(http, "get", fake_get)
    return calls


@pytest.mark.parametrize("link_type, pub_date, start, expected", [
    ("ctgov_result", "2022-01-01", "2020-06-01", "results_candidate"),
    ("pubmed_si", "2022-01-01", None, "results_candidate"),
    ("ctgov_derived", None, "2020-06-01", "results_candidate"),
    ("ctgov_result", "2005-01-01", "2020-06-01", "background"),
    ("europepmc_mention", "2022-01-01", "2020-06-01", "mention_only"),
    ("europepmc_drug_name", "2022-01-01", "2020-06-01", "mention_only"),
])
def test_link_strength(link_type, pub_date, start, expected):
    assert tools.link_strength(link_type, pub_date, start) == expected


def test_reviews_only_is_a_citable_no_results_publication():
    rows = db.run_select(f"SELECT DISTINCT link_type FROM publications WHERE nct_id = '{NEVER_POSTED}'")["rows"]
    assert {r["link_type"] for r in rows} == {"europepmc_mention"}
    state = RunState("q")
    result = tools.trial_publications(state, NEVER_POSTED)
    assert result["results_candidates"] == 0 and result["publications"]
    assert all(p["link_strength"] == "mention_only" for p in result["publications"])
    record = state.store.get(result["evidence_id"])
    assert result["evidence_id"].startswith("pubmed:none:")
    assert record.title.startswith(f"No results publication found for {NEVER_POSTED}") and "only mention it" in record.title
    assert len(record.data["mentions"]) == len(result["publications"])
    assert "pubmed_si" in result["searched"]  # tried live PubMed for a paper newer than the snapshot


def test_paper_from_before_the_trial_is_background(pubmed_finds_nothing):
    result = tools.trial_publications(RunState("q"), BACKGROUND)
    assert {p["link_strength"] for p in result["publications"]} == {"background"}
    assert result["results_candidates"] == 0 and result["evidence_id"].startswith("pubmed:none:")


def test_linked_paper_is_a_candidate_without_going_live(pubmed_finds_nothing):
    result = tools.trial_publications(RunState("q"), LINKED)
    assert result["results_candidates"] >= 1 and "evidence_id" not in result
    assert result["publications"][0]["link_strength"] == "results_candidate"
    assert pubmed_finds_nothing == []


def test_timeline_skips_mentions():
    state = RunState("q")
    for nct in (NEVER_POSTED, LINKED):
        tools._add_trial(state, db.trial_record(nct))
        tools.trial_publications(state, nct)
    by_trial = {t["nct_id"]: t for t in report.build_timeline(state, [f"ctgov:{NEVER_POSTED}", f"ctgov:{LINKED}"])}
    kinds = lambda nct: [e["kind"] for e in by_trial[nct]["events"]]  # noqa: E731
    assert "publication" not in kinds(NEVER_POSTED)
    assert "publication" in kinds(LINKED)


def test_publication_rate_ignores_mentions():
    stats = db.run_select(tools.STATS_SQL)["rows"][0]
    any_link = db.run_select("""SELECT round(100.0 * count(*) FILTER (WHERE EXISTS (SELECT 1 FROM publications p WHERE p.nct_id = d.nct_id))
                                / count(*), 1) AS pct FROM trial_derived d WHERE d.stopped""")["rows"][0]["pct"]
    assert stats["pct_stopped_with_publication"] < any_link
    assert stats["pct_stopped_with_publication"] + stats["pct_stopped_mentioned_only"] <= any_link + 0.1


def test_cant_tell_drops_model_budget_sentences_but_keeps_the_real_note():
    from ghost.report import render
    from ghost.pipeline import Claim, WriterReport

    state = RunState("q")
    tools._add_trial(state, db.trial_record(NEVER_POSTED))
    report = WriterReport(
        answer=[Claim(text="The registry says enrollment was slow.", citations=[f"ctgov:{NEVER_POSTED}"])],
        evidence=[], differences=[], timeline_text="",
        cant_tell=["We cannot tell the real reason beyond the registry text.",
                   "We also cannot tell if the research stopped early because of the time budget.",
                   "Our research into the SEC filings stopped early because of the research round budget."])
    stats = {"citations_checked": 1, "removed": 0}
    assert render(state, report, stats)["report"]["cant_tell"] == ["We cannot tell the real reason beyond the registry text."]
    state.notes.append("Stopped after round 2 because the time budget was nearly used up.")
    assert render(state, report, stats)["report"]["cant_tell"][-1].startswith("Stopped after round 2")


def test_writer_prompt_rules():
    from ghost.config import ROOT

    text = (ROOT / "prompts" / "writer.md").read_text()
    assert "never the articles that merely mention the trial" in text
    assert "the registry has no stop date" in text
    assert "—" not in text
