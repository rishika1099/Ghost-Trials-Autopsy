"""/chat keeps the Project 1 shape exactly: {response, session_id, tool_calls}, and each tool call is
{name, args, result} plus an agent field naming which agent made it."""

from fastapi.testclient import TestClient

import app as web
from tests.conftest import live

AGENTS = {"lead", "researcher:trials", "researcher:disclosures", "researcher:publications", "writer", "checker", "skeptic"}


def check_shape(body: dict) -> None:
    assert set(body) == {"response", "session_id", "tool_calls"}
    assert isinstance(body["response"], str) and body["response"]
    assert isinstance(body["session_id"], str) and body["session_id"]
    assert isinstance(body["tool_calls"], list)
    for call in body["tool_calls"]:
        assert set(call) == {"name", "args", "result", "agent"}, call
        assert call["agent"] in AGENTS, call["agent"]
        assert isinstance(call["name"], str) and isinstance(call["args"], dict) and isinstance(call["result"], str)


def test_chat_shape(stub_pipeline):
    body = TestClient(web.app).post("/chat", json={"message": "Did NCT01234567 post results?"}).json()
    check_shape(body)
    agents = {c["agent"] for c in body["tool_calls"]}
    assert {"lead", "researcher:trials", "writer", "checker", "skeptic"} <= agents


def test_session_id_is_kept(stub_pipeline):
    body = TestClient(web.app).post("/chat", json={"message": "NCT01234567 results?", "session_id": "abc"}).json()
    assert body["session_id"] == "abc"


def test_health():
    response = TestClient(web.app).get("/health")
    assert response.status_code == 200 and "snapshot_date" in response.json()


@live
def test_chat_shape_live():
    body = TestClient(web.app).post("/chat", json={"message": "Why do trials fail?"}).json()
    check_shape(body)
