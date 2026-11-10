"""The Skeptic: a fifth agent shape that reads the checked report like an editor. Its sentences cite nothing, so
the Checker's rules screen them against the whole evidence store; it is skipped, never fatal, when time is short."""

import asyncio

import pytest

from ghost import pipeline
from ghost.pipeline import Claim, SkepticNotes, WriterReport
from ghost.state import RunState
from tests.conftest import REAL_RUN_SKEPTIC, live


def state_with_trial() -> RunState:
    state = RunState(question="Why did NCT01234567 stop?")
    state.store.add("ctgov:NCT01234567", "A test trial", "https://clinicaltrials.gov/study/NCT01234567",
                    {"nct_id": "NCT01234567", "overall_status": "TERMINATED", "why_stopped": "Business decision",
                     "start_date": "2017-01-01", "primary_completion_date": "2018-06-01"})
    return state


REPORT = WriterReport(answer=[Claim(text="NCT01234567 was terminated for a business decision.", citations=["ctgov:NCT01234567"])],
                      evidence=[], differences=[], cant_tell=["Only the stated reason is known."], timeline_text="")


def test_screen_drops_invented_dates_and_accusations():
    state = state_with_trial()
    notes = SkepticNotes(strength="moderate", strength_reason="It rests on the registry entry.",
                         alternatives=["Results may have been presented at a conference.",
                                       "A partner may have taken over the drug on 2019-03-04.",  # date in no record
                                       "The company concealed the results."],  # overreaching
                         questions=["Will NCT01234567 post results?", "Why did you hide the data?"])
    screened, dropped = pipeline.screen_skeptic(state, notes)
    assert screened.alternatives == ["Results may have been presented at a conference."]
    assert screened.questions == ["Will NCT01234567 post results?"]
    assert {d["kind"] for d in dropped} == {"alternative", "question"} and len(dropped) == 3


def test_screen_keeps_dates_that_are_in_the_records():
    state = state_with_trial()
    notes = SkepticNotes(strength="weak", strength_reason="One record.", alternatives=["Primary completion was 2018-06-01, so results may still be coming."])
    screened, dropped = pipeline.screen_skeptic(state, notes)
    assert screened.alternatives and not dropped


def test_report_has_skeptic_section_and_trace(stub_pipeline):
    result = asyncio.run(pipeline.investigate("Why did NCT01234567 stop?"))
    assert "## Before you publish: the Skeptic's read" in result["markdown"]
    assert result["markdown"].index("## What the data can't tell us") < result["markdown"].index("## Before you publish") < result["markdown"].index("## Sources")
    assert result["skeptic"]["strength"] == "moderate" and result["report"]["skeptic"]["questions"]
    calls = [c for c in result["tool_calls"] if c["agent"] == "skeptic"]
    assert len(calls) == 1 and calls[0]["name"] == "review_report"


def test_skeptic_failure_keeps_the_report(stub_pipeline, monkeypatch):
    async def broken(state, report):
        raise ValueError("bad JSON")

    monkeypatch.setattr(pipeline, "run_skeptic", broken)
    result = asyncio.run(pipeline.investigate("Why did NCT01234567 stop?"))
    assert result["kind"] == "report" and result["skeptic"] is None
    assert "Before you publish" not in result["markdown"]
    assert any("Skeptic did not finish" in n for n in result["trace"]["notes"])


def test_skeptic_skipped_when_time_is_short():
    state = state_with_trial()
    state.budget_s = pipeline.SKEPTIC_MIN_S - 1
    assert asyncio.run(pipeline.skeptic_review(state, REPORT)) is None
    assert any("Skeptic was skipped" in n for n in state.notes)


def test_skeptic_skipped_for_an_empty_report():
    empty = REPORT.model_copy(update={"answer": [], "evidence": []})
    assert asyncio.run(pipeline.skeptic_review(state_with_trial(), empty)) is None


def test_skeptic_output_has_no_dashes(monkeypatch):
    async def dashed(state, report):
        return SkepticNotes(strength="weak", strength_reason="One record — the registry.",
                            alternatives=["Results may come in 2018–2019."], questions=["Will results be posted?"])

    monkeypatch.setattr(pipeline, "run_skeptic", dashed)
    out = asyncio.run(pipeline.skeptic_review(state_with_trial(), REPORT))
    text = " ".join([out["strength_reason"], *out["alternatives"], *out["questions"]])
    assert "—" not in text and "–" not in text


@live
def test_skeptic_live():
    state = state_with_trial()
    notes = asyncio.run(REAL_RUN_SKEPTIC(state, REPORT))
    screened, _ = pipeline.screen_skeptic(state, notes)
    assert notes.strength in ("strong", "moderate", "weak")
    assert 1 <= len(screened.questions) <= 4 and screened.alternatives
