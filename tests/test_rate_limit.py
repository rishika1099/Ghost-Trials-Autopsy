"""The public site spends model credits on every investigation, so each visitor gets a few per window."""

from fastapi.testclient import TestClient

import app as web
from tests.test_shape import check_shape


def test_chat_is_limited_per_visitor_with_the_same_shape(stub_pipeline, monkeypatch):
    monkeypatch.setattr(web, "RATE_LIMIT", 2)
    client = TestClient(web.app)
    for _ in range(2):
        assert client.post("/chat", json={"message": "Did NCT01234567 post results?"}).status_code == 200
    limited = client.post("/chat", json={"message": "Did NCT01234567 post results?"})
    assert limited.status_code == 429
    body = limited.json()
    assert set(body) == {"response", "session_id", "tool_calls"} and body["tool_calls"] == []
    assert "try again" in body["response"]
    assert stub_pipeline["researchers"] == 6  # the limited call ran no research


def test_visitors_are_counted_separately(stub_pipeline, monkeypatch):
    monkeypatch.setattr(web, "RATE_LIMIT", 1)
    client = TestClient(web.app)
    a = {"X-Forwarded-For": "203.0.113.1"}
    b = {"X-Forwarded-For": "203.0.113.2, 10.0.0.1"}
    assert client.post("/chat", json={"message": "NCT01234567?"}, headers=a).status_code == 200
    assert client.post("/chat", json={"message": "NCT01234567?"}, headers=a).status_code == 429
    assert client.post("/chat", json={"message": "NCT01234567?"}, headers=b).status_code == 200


def test_stream_is_limited_with_an_error_event(stub_pipeline, monkeypatch):
    monkeypatch.setattr(web, "RATE_LIMIT", 1)
    client = TestClient(web.app)
    client.post("/chat", json={"message": "NCT01234567?"})  # /chat and /run share one count
    text = client.get("/run", params={"question": "NCT01234567?"}).text
    assert '"type": "error"' in text and "try again" in text


def test_ask_is_limited(monkeypatch):
    monkeypatch.setattr(web, "ASK_RATE_LIMIT", 1)

    async def fake(question):
        return {"ok": True, "answer": "fine"}

    monkeypatch.setattr(web.analyst, "ask", fake)
    client = TestClient(web.app)
    assert client.post("/api/ask", json={"question": "x"}).status_code == 200
    limited = client.post("/api/ask", json={"question": "x"})
    assert limited.status_code == 429 and limited.json()["rate_limited"]


def test_instant_views_are_never_limited(monkeypatch):
    monkeypatch.setattr(web, "RATE_LIMIT", 1)
    monkeypatch.setattr(web, "ASK_RATE_LIMIT", 1)
    client = TestClient(web.app)
    for _ in range(5):
        assert client.get("/api/ledger").status_code == 200 and client.get("/health").status_code == 200


def test_zero_turns_the_limit_off(stub_pipeline, monkeypatch):
    monkeypatch.setattr(web, "RATE_LIMIT", 0)
    client = TestClient(web.app)
    assert all(client.post("/chat", json={"message": "NCT01234567?"}).status_code == 200 for _ in range(3))
