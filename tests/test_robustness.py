"""Failure handling: HTTP retries only what can succeed, the cache survives bad files, and the single-agent
steps (Lead plan, Writer, Checker) get one retry and a time limit instead of failing the whole request."""

import asyncio

import httpx
import pytest

from ghost import http, pipeline


class FakeClient:
    """Answers each GET with the next status code and counts the calls."""

    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = 0

    def get(self, url, params=None, headers=None):
        self.calls += 1
        status = self.statuses.pop(0)
        if status == "network":
            raise httpx.ConnectError("down")
        return httpx.Response(status, json={"ok": status}, request=httpx.Request("GET", url))


@pytest.fixture
def fake_http(monkeypatch, tmp_path):
    sleeps = []
    monkeypatch.setattr(http, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(http.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(http, "_wait_turn", lambda host: None)

    def install(statuses):
        client = FakeClient(statuses)
        monkeypatch.setattr(http, "_client", client)
        return client

    return install, sleeps


# --- HTTP ---


def test_missing_sec_user_agent_fails_at_once(fake_http, monkeypatch):
    install, sleeps = fake_http
    client = install([200])
    monkeypatch.setattr(http, "SEC_USER_AGENT", "")
    with pytest.raises(http.SourceError, match="SEC_USER_AGENT"):
        http.get("https://efts.sec.gov/LATEST/search-index", {"q": "x"})
    assert client.calls == 0 and sleeps == []


def test_client_error_is_not_retried(fake_http):
    install, sleeps = fake_http
    client = install([403, 200])
    with pytest.raises(http.SourceError, match="403"):
        http.get("https://clinicaltrials.gov/api/v2/studies/NCT01234567")
    assert client.calls == 1 and sleeps == []


def test_server_error_is_retried_then_succeeds(fake_http):
    install, sleeps = fake_http
    client = install([503, "network", 200])
    assert http.get("https://clinicaltrials.gov/api/v2/studies/NCT01234567") == {"ok": 200}
    assert client.calls == 3 and len(sleeps) == 2


def test_gives_up_after_max_retries_without_a_last_sleep(fake_http):
    install, sleeps = fake_http
    client = install([503] * http.MAX_RETRIES)
    with pytest.raises(http.SourceError, match="failed after"):
        http.get("https://clinicaltrials.gov/api/v2/studies/NCT01234567")
    assert client.calls == http.MAX_RETRIES and len(sleeps) == http.MAX_RETRIES - 1


def test_corrupt_cache_file_is_a_miss_and_gets_rewritten(fake_http):
    install, _ = fake_http
    url = "https://clinicaltrials.gov/api/v2/studies/NCT01234567"
    path = http._cache_path(url, None)
    path.parent.mkdir(parents=True)
    path.write_text('{"url": "half a fi')  # what a crash mid-write used to leave behind
    client = install([200])
    assert http.get(url) == {"ok": 200}
    assert client.calls == 1
    assert http.get(url) == {"ok": 200} and client.calls == 1  # now served from the repaired cache
    assert not list(path.parent.glob("*.tmp"))  # the temp file was renamed into place


# --- Pipeline steps ---


async def test_writer_failure_is_retried_once(stub_pipeline, monkeypatch):
    real_writer, tries = pipeline.run_writer, []

    async def flaky(state, findings):
        tries.append(1)
        if len(tries) == 1:
            raise ValueError("bad JSON from the model")
        return await real_writer(state, findings)

    monkeypatch.setattr(pipeline, "run_writer", flaky)
    out = await pipeline.investigate("NCT01234567")
    assert len(tries) == 2
    assert out["kind"] == "report"
    assert any("Writer failed once" in n for n in out["trace"]["notes"])


async def test_writer_that_keeps_failing_falls_back_to_findings(stub_pipeline, monkeypatch):
    async def broken(state, findings):
        raise ValueError("bad JSON from the model")

    monkeypatch.setattr(pipeline, "run_writer", broken)
    out = await pipeline.investigate("NCT01234567")
    assert out["kind"] == "report"
    assert "The trial was terminated." in out["markdown"]  # the researcher's own cited finding
    assert out["checker"]["citations_checked"] >= 1


async def test_writer_that_hangs_is_stopped_by_the_budget(stub_pipeline, monkeypatch):
    async def hangs(state, findings):
        await asyncio.sleep(60)

    monkeypatch.setattr(pipeline, "run_writer", hangs)
    monkeypatch.setattr(pipeline, "MIN_STEP_S", 0.3)
    monkeypatch.setattr(pipeline, "CHECKER_RESERVE_S", 0)
    started = asyncio.get_running_loop().time()
    out = await pipeline.investigate("NCT01234567", budget_s=1.5)
    assert asyncio.get_running_loop().time() - started < 10
    assert out["kind"] == "report"
    assert any("time budget" in n for n in out["trace"]["notes"])


async def test_checker_that_hangs_is_stopped_by_the_budget(stub_pipeline, monkeypatch):
    async def hangs(state, claims, **kwargs):
        await asyncio.sleep(60)

    monkeypatch.setattr(pipeline, "run_checker", hangs)
    monkeypatch.setattr(pipeline, "MIN_STEP_S", 0.3)
    out = await pipeline.investigate("NCT01234567", budget_s=1.5)
    assert out["checker"]["model_pass"] is False
    assert any("Checker model pass hit the time budget" in n for n in out["trace"]["notes"])


async def test_lead_plan_failure_is_retried_once(stub_pipeline, monkeypatch):
    real_plan, tries = pipeline.run_lead_plan, []

    async def flaky(state):
        tries.append(1)
        if len(tries) == 1:
            raise RuntimeError("503 from Vertex")
        return await real_plan(state)

    monkeypatch.setattr(pipeline, "run_lead_plan", flaky)
    out = await pipeline.investigate("NCT01234567")
    assert len(tries) == 2 and out["kind"] == "report"


async def test_lead_plan_that_hangs_raises_a_clear_error(stub_pipeline, monkeypatch):
    async def hangs(state):
        await asyncio.sleep(60)

    monkeypatch.setattr(pipeline, "run_lead_plan", hangs)
    monkeypatch.setattr(pipeline, "MIN_STEP_S", 0.3)
    with pytest.raises(RuntimeError, match="did not finish planning"):
        await pipeline.investigate("NCT01234567", budget_s=1.0)
