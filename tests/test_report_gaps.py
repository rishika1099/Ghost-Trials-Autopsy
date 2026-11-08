"""The report never has an empty limits section, the Checker also checks the timeline text, and
clarifications waiting for a reply expire."""

import app as app_module
from ghost import pipeline


async def test_cant_tell_is_never_empty(stub_pipeline, monkeypatch):
    real_writer = pipeline.run_writer

    async def writer(state, findings):
        report = await real_writer(state, findings)
        # The only limit the model gave is about our own run limits, which the renderer filters out.
        return report.model_copy(update={"cant_tell": ["We hit the time budget."]})

    monkeypatch.setattr(pipeline, "run_writer", writer)
    out = await pipeline.investigate("NCT01234567")
    assert out["report"]["cant_tell"]
    assert "No SEC filing was found" in out["markdown"]


async def test_timeline_text_with_an_unsupported_date_is_replaced(stub_pipeline, monkeypatch):
    real_writer = pipeline.run_writer

    async def writer(state, findings):
        report = await real_writer(state, findings)
        return report.model_copy(update={"timeline_text": "Started 2017-01-01. Stopped 2020-03-15."})  # 2020-03-15 is invented

    monkeypatch.setattr(pipeline, "run_writer", writer)
    out = await pipeline.investigate("NCT01234567")
    assert out["checker"]["timeline_replaced"] is True
    assert "2020-03-15" not in out["markdown"]
    assert "NCT01234567: Start 2017-01-01" in out["report"]["timeline_text"]


async def test_supported_timeline_text_is_kept(stub_pipeline):
    out = await pipeline.investigate("NCT01234567")  # the stub writer says "Started 2017-01-01."
    assert out["checker"]["timeline_replaced"] is False
    assert out["report"]["timeline_text"] == "Started 2017-01-01."


def test_clarifications_expire(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(app_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(app_module, "pending_clarifications", {})
    app_module.remember_clarification("s1", "Why do trials fail?")
    assert app_module.with_clarification("s1", "Alzheimer's, 2015 to 2023").startswith("Why do trials fail?")
    app_module.remember_clarification("s1", "Why do trials fail?")
    now[0] += app_module.CLARIFY_TTL_S + 1
    assert app_module.with_clarification("s1", "a new question") == "a new question"


def test_clarifications_are_capped(monkeypatch):
    monkeypatch.setattr(app_module, "pending_clarifications", {})
    for i in range(app_module.CLARIFY_MAX + 50):
        app_module.remember_clarification(f"s{i}", "q")
    assert len(app_module.pending_clarifications) == app_module.CLARIFY_MAX
    assert "s0" not in app_module.pending_clarifications
