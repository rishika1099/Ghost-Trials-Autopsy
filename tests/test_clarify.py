"""Vague questions get a clarification and no research."""

from ghost import pipeline
from ghost.pipeline import LeadPlan
from tests.conftest import live


async def test_clarify_makes_no_researcher_calls(stub_pipeline):
    stub_pipeline["plan"] = LeadPlan(decision="clarify", message="Which trials do you mean?",
                                     options=["Industry phase 2 and 3 Alzheimer's trials stopped 2015 to 2023, by stated reason", "One sponsor (which?)"])
    result = await pipeline.investigate("Why do trials fail?")
    assert result["kind"] == "clarify"
    assert stub_pipeline["researchers"] == 0
    assert not any(c["agent"].startswith("researcher") for c in result["tool_calls"])
    assert "Which trials do you mean?" in result["markdown"] and "One sponsor" in result["markdown"]


@live
async def test_clarify_live():
    result = await pipeline.investigate("Why do trials fail?")
    assert result["kind"] == "clarify", result["markdown"]
    assert not any(c["agent"].startswith("researcher") for c in result["tool_calls"])
    assert 2 <= len(result["options"]) <= 4


@live
async def test_specific_question_is_not_clarified():
    plan = await pipeline.run_lead_plan(pipeline.RunState(question="Why was trial NCT02008682 stopped, and were its results posted?"))
    assert plan.decision == "research"
