"""Shared stubs. Offline tests replace the model-calling steps of ghost.pipeline with fakes, so they
test the pipeline's logic (fan-out, round cap, gate, citation check, response shape) without Gemini.
Tests marked live call the real models: run them with LIVE=1."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.items import ModelResponse  # noqa: E402
from agents.models.interface import Model  # noqa: E402
from agents.usage import Usage  # noqa: E402
from openai.types.responses import ResponseOutputMessage, ResponseOutputText  # noqa: E402

from ghost import pipeline  # noqa: E402
from ghost.pipeline import Brief, Claim, CheckerVerdicts, Finding, Findings, LeadPlan, LeadReview, WriterReport  # noqa: E402

LIVE = os.environ.get("LIVE") == "1"
live = pytest.mark.skipif(not LIVE, reason="calls Gemini; run with LIVE=1")


class FakeModel(Model):
    """A model that answers every call with a fixed final output and records what it was sent."""

    def __init__(self, output: str):
        self.output = output
        self.calls: list[dict] = []

    async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs):
        self.calls.append({"system": system_instructions, "input": input})
        await asyncio.sleep(0.3)  # long enough that sequential runs could not overlap
        message = ResponseOutputMessage(id="m1", type="message", role="assistant", status="completed",
                                        content=[ResponseOutputText(type="output_text", text=self.output, annotations=[])])
        return ModelResponse(output=[message], usage=Usage(), response_id=None)

    def stream_response(self, *args, **kwargs):
        raise NotImplementedError


def research_plan(lanes=("trials", "disclosures", "publications")) -> LeadPlan:
    return LeadPlan(decision="research", message="", plan="Look up the trial in all three lanes.",
                    briefs=[Brief(lane=lane, brief=f"Brief for {lane}: NCT01234567") for lane in lanes])


@pytest.fixture
def stub_pipeline(monkeypatch):
    """Stub every model step. Returns a dict the test can change: plan, review, and call counters."""
    calls = {"researchers": 0, "reviews": 0, "plan": research_plan(), "review": LeadReview(done=True, gaps=[])}

    async def plan(state):
        state.record_call("lead", "query_trials_sql", {"sql": "SELECT 1"}, "1 rows")
        return calls["plan"]

    async def review(state, plan, findings):
        calls["reviews"] += 1
        return calls["review"]

    async def researcher(state, brief, key):
        calls["researchers"] += 1
        evidence_id = state.store.add("ctgov:NCT01234567", "A test trial", "https://clinicaltrials.gov/study/NCT01234567",
                                      {"nct_id": "NCT01234567", "overall_status": "TERMINATED", "why_stopped": "Business decision",
                                       "start_date": "2017-01-01", "primary_completion_date": "2018-06-01",
                                       "results_due_date": "2019-06-01", "has_results": False})
        state.record_call(f"researcher:{brief.lane}", "query_trials_sql", {"sql": "SELECT ..."}, "1 rows")
        await asyncio.sleep(0.2)
        return Findings(findings=[Finding(claim="The trial was terminated.", evidence_ids=[evidence_id], confidence="high")], gaps=[])

    async def writer(state, findings):
        return WriterReport(answer=[Claim(text="The registry lists NCT01234567 as terminated for a business decision.",
                                          citations=["ctgov:NCT01234567"])],
                            evidence=[Claim(text="No results are posted.", citations=["ctgov:NCT01234567"])],
                            differences=[], cant_tell=["The stated reason is all we know."], timeline_text="Started 2017-01-01.")

    async def checker(state, claims):
        return CheckerVerdicts(verdicts=[])

    monkeypatch.setattr(pipeline, "run_lead_plan", plan)
    monkeypatch.setattr(pipeline, "run_lead_review", review)
    monkeypatch.setattr(pipeline, "run_researcher", researcher)
    monkeypatch.setattr(pipeline, "run_writer", writer)
    monkeypatch.setattr(pipeline, "run_checker", checker)
    return calls


def fake_findings_json() -> str:
    return json.dumps({"findings": [{"claim": "x", "evidence_ids": [], "confidence": "low", "notes": ""}], "gaps": []})
