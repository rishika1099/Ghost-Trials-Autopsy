"""The Lead's fan-out runs researchers in parallel (their time spans overlap), each in a fresh context
(its first model input is only its own system prompt and its brief)."""

import json

import pytest

from ghost import pipeline
from ghost.state import RunState
from tests.conftest import FakeModel, fake_findings_json, research_plan


@pytest.fixture
def fake_models(monkeypatch):
    made: list[FakeModel] = []

    def model(name):
        made.append(FakeModel(fake_findings_json()))
        return made[-1]

    monkeypatch.setattr(pipeline, "model", model)
    return made


async def test_researchers_overlap_and_start_fresh(fake_models):
    state = RunState(question="Tell me about NCT01234567")
    state.record_call("lead", "plan", {}, "lead conversation that researchers must never see")
    briefs = research_plan().briefs
    results = await pipeline.dispatch_researchers(state, briefs)

    assert len(results) == 3
    # Parallel: every researcher started before any finished.
    starts, ends = [t["start"] for t in state.timings], [t["end"] for t in state.timings]
    assert max(starts) < min(ends), state.timings
    # Fresh context: each researcher's first input is [system prompt, its own brief] and nothing else.
    assert len(state.first_contexts) == 3
    for key, context in state.first_contexts.items():
        messages = context["messages"]
        lane = context["agent"].split(":")[1]
        assert [m["role"] for m in messages] == ["system", "user"], messages
        assert messages[0]["content"] == pipeline.researcher(lane).instructions
        assert messages[1]["content"] == f"Brief for {lane}: NCT01234567"
        assert "lead conversation" not in json.dumps(messages)
        assert all(f"Brief for {other}" not in json.dumps(messages) for other in pipeline.LANES if other != lane)


async def test_fan_out_is_one_lead_call(stub_pipeline):
    state = RunState(question="NCT01234567")
    await pipeline.research(state, research_plan())
    dispatches = [c for c in state.tool_calls if c["name"] == "dispatch_researchers"]
    assert len(dispatches) == 1 and len(dispatches[0]["args"]["briefs"]) == 3
    assert stub_pipeline["researchers"] == 3
