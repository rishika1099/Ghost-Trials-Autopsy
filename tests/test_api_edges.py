"""/chat, /run, /health and /api/meta at their edges: bad bodies, empty and huge messages, a pipeline that
crashes, the clarification follow-up, and the live stream's event order. Every /chat reply keeps the Project 1
shape, including errors."""

import json

from fastapi.testclient import TestClient

import app as web
from ghost import pipeline
from ghost.pipeline import LeadPlan
from tests.test_shape import check_shape

client = TestClient(web.app)


def test_missing_message_is_a_422_not_a_crash():
    assert client.post("/chat", json={}).status_code == 422
    assert client.post("/chat", json={"message": None}).status_code == 422
    assert client.post("/chat", content="not json", headers={"Content-Type": "application/json"}).status_code == 422


def test_empty_message_keeps_the_shape(stub_pipeline):
    body = client.post("/chat", json={"message": ""}).json()
    check_shape(body)
    assert body["tool_calls"] == [] and "NCT ID" in body["response"]


def test_huge_message_keeps_the_shape(stub_pipeline):
    body = client.post("/chat", json={"message": "x" * 50_000}).json()
    check_shape(body)
    assert "characters" in body["response"]


def test_pipeline_crash_is_shown_in_the_reply_not_a_500(monkeypatch):
    async def crash(question, **kwargs):
        raise PermissionError("Vertex AI quota exceeded")

    monkeypatch.setattr(web, "investigate", crash)
    response = client.post("/chat", json={"message": "NCT01234567", "session_id": "s1"})
    assert response.status_code == 200
    body = response.json()
    check_shape(body)
    assert body["response"].startswith("Research failed: PermissionError") and body["session_id"] == "s1"


def test_extra_request_fields_are_ignored(stub_pipeline):
    body = client.post("/chat", json={"message": "NCT01234567 results?", "stream": True, "user": "x"}).json()
    check_shape(body)


def test_clarification_reply_is_joined_to_the_question(stub_pipeline, monkeypatch):
    seen = []
    real = pipeline.investigate

    async def spy(question, **kwargs):
        seen.append(question)
        return await real(question, **kwargs)

    monkeypatch.setattr(web, "investigate", spy)
    stub_pipeline["plan"] = LeadPlan(decision="clarify", message="Which trials?", options=["One sponsor", "One drug"])
    first = client.post("/chat", json={"message": "Why do trials fail?", "session_id": "c1"}).json()
    check_shape(first)
    assert "Which trials?" in first["response"]
    assert not [c for c in first["tool_calls"] if c["agent"].startswith("researcher")]

    stub_pipeline["plan"] = pipeline.LeadPlan(decision="research", message="", briefs=[
        pipeline.Brief(lane="trials", brief="Entero trials")])
    client.post("/chat", json={"message": "One sponsor: Entero Therapeutics", "session_id": "c1"})
    assert seen[1] == "Why do trials fail?\nClarification from the user: One sponsor: Entero Therapeutics"

    client.post("/chat", json={"message": "Another question", "session_id": "c1"})
    assert seen[2] == "Another question"  # the clarification is used once


def test_clarification_does_not_leak_across_sessions(stub_pipeline, monkeypatch):
    seen = []
    real = pipeline.investigate

    async def spy(question, **kwargs):
        seen.append(question)
        return await real(question, **kwargs)

    monkeypatch.setattr(web, "investigate", spy)
    stub_pipeline["plan"] = LeadPlan(decision="clarify", message="Which trials?", options=["a", "b"])
    client.post("/chat", json={"message": "Why do trials fail?", "session_id": "A"})
    client.post("/chat", json={"message": "NCT01234567", "session_id": "B"})
    assert seen[1] == "NCT01234567"


def test_refusal_is_not_remembered_as_a_clarification(stub_pipeline, monkeypatch):
    stub_pipeline["plan"] = LeadPlan(decision="refuse", message="No medical advice.", options=["x"])
    client.post("/chat", json={"message": "Should I take X?", "session_id": "r1"})
    assert "r1" not in web.pending_clarifications


def stream(question: str, **params) -> list[dict]:
    with client.stream("GET", "/run", params={"question": question, **params}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        return [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]


def test_stream_starts_ends_with_done_and_shows_every_agent(stub_pipeline):
    events = stream("Why did NCT01234567 stop?")
    assert events[0]["type"] == "start" and events[-1]["type"] == "done"
    done = events[-1]
    assert done["kind"] == "report" and "findings" not in done and done["sources"]
    agents = {e["agent"] for e in events if e["type"] == "agent"}
    assert {"lead", "researcher:trials", "researcher:disclosures", "researcher:publications", "writer", "checker"} <= agents
    assert not any(e["type"] == "context" for e in events)


def test_stream_reports_errors_as_an_event(monkeypatch):
    async def crash(question, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(web, "investigate", crash)
    events = stream("NCT01234567")
    assert events[-1] == {"type": "error", "message": "RuntimeError: boom"}


def test_stream_keeps_the_session_id(stub_pipeline):
    assert stream("NCT01234567", session_id="keep-me")[0]["session_id"] == "keep-me"


def test_meta_and_index():
    meta = client.get("/api/meta").json()
    assert meta["snapshot_date"] and {t["table_name"] for t in meta["tables"]} >= {"trials", "trial_derived"}
    page = client.get("/")
    assert page.status_code == 200 and "Ghost Trials" in page.text and page.headers["cache-control"] == "no-cache"


def test_unknown_route_is_404():
    assert client.get("/nope").status_code == 404
    assert client.get("/chat").status_code == 405
