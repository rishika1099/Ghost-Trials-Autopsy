"""Pipeline branches the main tests don't reach: a researcher that crashes, a Lead review that fails, too many
gaps, refusals, empty or huge questions, a report whose every claim is removed, and the evidence store's merge."""

import pytest

from ghost import pipeline
from ghost.evidence import EvidenceStore
from ghost.pipeline import Brief, Claim, Gap, LeadPlan, LeadReview, WriterReport
from ghost.report import render
from ghost.state import RunState
from tests.conftest import research_plan


async def test_one_researcher_crashing_does_not_sink_the_others(stub_pipeline, monkeypatch):
    real = pipeline.run_researcher

    async def flaky(state, brief, key):
        if brief.lane == "disclosures":
            raise ConnectionError("EDGAR down")
        return await real(state, brief, key)

    monkeypatch.setattr(pipeline, "run_researcher", flaky)
    state = RunState(question="NCT01234567")
    findings = await pipeline.research(state, research_plan())
    by_lane = {f["lane"]: f for f in findings}
    assert by_lane["trials"]["findings"] and by_lane["publications"]["findings"]
    assert not by_lane["disclosures"]["findings"]
    assert "ConnectionError" in by_lane["disclosures"]["gaps"][0]
    assert len(state.timings) == 3  # the crashed one still has start and end times


async def test_failed_lead_review_writes_with_what_it_has(stub_pipeline, monkeypatch):
    async def broken(state, plan, findings):
        raise ValueError("bad JSON")

    monkeypatch.setattr(pipeline, "run_lead_review", broken)
    state = RunState(question="NCT01234567")
    findings = await pipeline.research(state, research_plan())
    assert state.rounds == 1 and findings
    assert any("Lead review failed" in n for n in state.notes)


async def test_at_most_three_gap_briefs_per_round(stub_pipeline):
    gaps = [Gap(lane=lane, description=f"gap {i}", brief=f"brief {i}")
            for i, lane in enumerate(["trials", "disclosures", "publications", "trials", "disclosures"])]
    stub_pipeline["review"] = LeadReview(done=False, gaps=gaps)
    state = RunState(question="NCT01234567")
    await pipeline.research(state, research_plan())
    assert len([t for t in state.timings if t["round"] == 2]) == 3


async def test_gaps_reported_but_done_stops(stub_pipeline):
    stub_pipeline["review"] = LeadReview(done=True, gaps=[Gap(lane="trials", description="x", brief="y")])
    state = RunState(question="NCT01234567")
    await pipeline.research(state, research_plan())
    assert state.rounds == 1


async def test_plan_without_briefs_sends_every_lane(stub_pipeline):
    state = RunState(question="NCT01234567")
    await pipeline.research(state, LeadPlan(decision="research", message="", briefs=[]))
    assert {t["agent"] for t in state.timings} == {"researcher:trials", "researcher:disclosures", "researcher:publications"}


async def test_refusal_does_no_research(stub_pipeline):
    stub_pipeline["plan"] = LeadPlan(decision="refuse", message="We can't give medical advice.",
                                     options=["Why did NCT01234567 stop?"])
    result = await pipeline.investigate("Should I take drug X?")
    assert result["kind"] == "refuse" and stub_pipeline["researchers"] == 0
    assert "medical advice" in result["markdown"] and "NCT01234567" in result["markdown"]


@pytest.mark.parametrize("question", ["", "   ", "\n\t"])
async def test_empty_question_never_calls_a_model(stub_pipeline, monkeypatch, question):
    async def boom(state):
        raise AssertionError("the Lead should not run")

    monkeypatch.setattr(pipeline, "run_lead_plan", boom)
    result = await pipeline.investigate(question)
    assert result["kind"] == "refuse" and result["tool_calls"] == [] and result["options"]


async def test_huge_question_never_calls_a_model(stub_pipeline, monkeypatch):
    async def boom(state):
        raise AssertionError("the Lead should not run")

    monkeypatch.setattr(pipeline, "run_lead_plan", boom)
    result = await pipeline.investigate("NCT01234567 " * 1000)
    assert result["kind"] == "refuse" and "characters" in result["markdown"]


async def test_question_at_the_limit_is_researched(stub_pipeline):
    question = ("Why did NCT01234567 stop? " * 400)[: pipeline.MAX_QUESTION_CHARS]
    assert (await pipeline.investigate(question))["kind"] == "report"


async def test_unicode_question_works(stub_pipeline):
    result = await pipeline.investigate("Pourquoi l'essai NCT01234567 s'est-il arrêté ? 为什么停止")
    assert result["kind"] == "report"


def _state_with_record() -> RunState:
    state = RunState(question="NCT01234567")
    state.store.add("ctgov:NCT01234567", "A test trial", "https://clinicaltrials.gov/study/NCT01234567",
                    {"nct_id": "NCT01234567", "start_date": "2017-01-01", "results_due_date": "2019-06-01"})
    return state


def test_report_with_every_claim_removed_still_renders_every_section():
    state = _state_with_record()
    stats = {"citations_checked": 2, "removed": 2}
    md = render(state, WriterReport(answer=[], evidence=[], differences=[], cant_tell=[], timeline_text=""), stats)["markdown"]
    for heading in ("## Answer", "## Timeline", "## Evidence", "## What the data can't tell us", "## Sources"):
        assert heading in md
    assert "does not support a direct answer" in md and "No claim survived" in md


def test_one_source_cited_many_times_gets_one_number():
    state = _state_with_record()
    claim = Claim(text="It started in 2017.", citations=["ctgov:NCT01234567"])
    out = render(state, WriterReport(answer=[claim], evidence=[claim, claim], differences=[], cant_tell=["x"],
                                     timeline_text=""), {"citations_checked": 3, "removed": 0})
    assert len(out["sources"]) == 1 and "[2]" not in out["markdown"]


async def test_duplicate_and_unknown_citations_are_cleaned(monkeypatch):
    state = _state_with_record()
    report = WriterReport(answer=[Claim(text="It started on 2017-01-01.",
                                        citations=["ctgov:NCT01234567", "ctgov:NCT01234567", "sec:made-up"])],
                          evidence=[Claim(text="Invented fact.", citations=["pubmed:000"])],
                          differences=[], cant_tell=["x"], timeline_text="")

    async def checker(state, claims, **kwargs):
        return pipeline.CheckerVerdicts(verdicts=[])

    monkeypatch.setattr(pipeline, "run_checker", checker)
    cleaned, stats = await pipeline.check_citations(state, report)
    assert cleaned.answer[0].citations == ["ctgov:NCT01234567"]
    assert cleaned.evidence == [] and stats["removed"] == 1 and stats["unknown_ids_dropped"] == 2


def test_fallback_report_skips_uncited_findings():
    findings = [{"lane": "trials", "findings": [{"claim": "cited", "evidence_ids": ["ctgov:NCT01234567"]},
                                                 {"claim": "uncited", "evidence_ids": []}]}]
    report = pipeline.fallback_report(findings)
    assert [c.text for c in report.answer + report.evidence] == ["cited"] and report.cant_tell


def test_fallback_report_with_no_findings_is_empty_but_valid():
    report = pipeline.fallback_report([])
    assert report.answer == [] and report.evidence == [] and report.cant_tell


def test_evidence_store_merges_without_erasing_fields():
    store = EvidenceStore()
    store.add("ctgov:NCT01234567", "Title", "https://x", {"status": "TERMINATED", "why_stopped": "funding"})
    store.add("ctgov:NCT01234567", "", "", {"status": "COMPLETED", "why_stopped": None, "enrollment": 40})
    record = store.get("ctgov:NCT01234567")
    assert record.data == {"status": "COMPLETED", "why_stopped": "funding", "enrollment": 40}
    assert record.title == "Title" and record.source_url == "https://x"


def test_evidence_store_compact_trims_long_records():
    store = EvidenceStore()
    store.add("sec:1", "Filing", "https://sec", {"text": "x" * 10_000})
    store.add("pubmed:2", "Paper", "https://pubmed", {"abstract": "short"})
    lines = store.compact(max_chars=500).splitlines()
    assert len(lines) == 2 and len(lines[0]) <= 505 and "short" in lines[1]
    assert store.compact(["missing:id"]) == ""


def test_brief_rejects_an_unknown_lane():
    with pytest.raises(Exception):
        Brief(lane="weather", brief="x")
