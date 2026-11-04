"""The Lead goes back for more when findings leave a gap, and stops at MAX_RESEARCH_ROUNDS."""

from ghost import config, pipeline
from ghost.pipeline import Gap, LeadReview
from ghost.state import RunState
from tests.conftest import research_plan

GAP = Gap(lane="disclosures", description="Sponsor matched to a CIK but no 8-K in the window",
          brief="Search 10-Q filings for CIK 0000000001 in 2018 for the drug name")


async def test_gap_triggers_second_round(stub_pipeline, monkeypatch):
    reviews = iter([LeadReview(done=False, gaps=[GAP]), LeadReview(done=True, gaps=[])])

    async def review(state, plan, findings):
        return next(reviews)

    monkeypatch.setattr(pipeline, "run_lead_review", review)
    state = RunState(question="NCT01234567")
    await pipeline.research(state, research_plan())
    assert state.rounds == 2
    second = [t for t in state.timings if t["round"] == 2]
    assert [t["agent"] for t in second] == ["researcher:disclosures"]  # only the lane the gap needs


async def test_stops_at_round_cap(stub_pipeline):
    stub_pipeline["review"] = LeadReview(done=False, gaps=[GAP])  # a gap that never closes
    state = RunState(question="NCT01234567")
    await pipeline.research(state, research_plan())
    assert state.rounds == config.MAX_RESEARCH_ROUNDS == 3
    assert stub_pipeline["reviews"] == config.MAX_RESEARCH_ROUNDS - 1  # no review after the last allowed round
    assert any("cap" in n for n in state.notes)


async def test_stops_near_budget(stub_pipeline):
    stub_pipeline["review"] = LeadReview(done=False, gaps=[GAP])
    state = RunState(question="NCT01234567")
    state.budget_s = config.WRITE_RESERVE_S + 10  # already inside the reserve: no second round
    await pipeline.research(state, research_plan())
    assert state.rounds == 1
    assert any("budget" in n for n in state.notes)
