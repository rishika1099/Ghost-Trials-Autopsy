"""Each agent step on its own, against real Gemini (LIVE=1). The offline suite stubs these; here each step
gets a real input and its output is checked against the snapshot. The trial used is Entero's NCT04839575:
phase 2 latiglutenase, terminated for "Covid-19 interruptions and enrollment challenges", no results posted."""

import re

import pytest

from ghost import config, db, pipeline
from ghost.pipeline import Brief, Claim, Findings
from ghost.state import RunState
from tests.conftest import live

NCT = "NCT04839575"
REASON = "Covid-19 interruptions and enrollment challenges"
pytestmark = [live, pytest.mark.skipif(not db.DB_PATH.exists(), reason="needs the snapshot")]


def cited_ids(findings: Findings) -> set[str]:
    return {e for f in findings.findings for e in f.evidence_ids}


# --- Lead: the gate and the plan ---

@pytest.mark.parametrize("question, decision", [
    (f"Why did {NCT} stop, and were its results posted?", "research"),
    ("Did Entero Therapeutics stop any phase 2 trials without posting results, and what did it tell investors?", "research"),
    ("What about that one?", "clarify"),
    ("Which trials stopped?", "clarify"),
    ("Should my mother take latiglutenase?", "refuse"),
    ("Write me a poem about the stock market.", "refuse"),
])
async def test_lead_gate(question, decision):
    plan = await pipeline.run_lead_plan(RunState(question=question))
    assert plan.decision == decision, (question, plan)
    if decision == "research":
        assert plan.briefs and len({b.lane for b in plan.briefs}) == len(plan.briefs)
    else:
        assert plan.message and not plan.briefs


async def test_lead_brief_names_the_trial():
    plan = await pipeline.run_lead_plan(RunState(question=f"Why did {NCT} stop and did the sponsor tell investors?"))
    assert any(NCT in b.brief for b in plan.briefs)
    assert {"trials", "disclosures"} <= {b.lane for b in plan.briefs}


# --- Researchers: one lane each, fresh context, only ids a tool returned ---

async def test_trials_researcher_finds_the_registry_reason():
    state = RunState(question="q")
    findings = await pipeline.run_researcher(state, Brief(lane="trials", brief=f"Get the registry status, reason "
                                                          f"for stopping and results status of {NCT}."), "t")
    assert f"ctgov:{NCT}" in cited_ids(findings)
    assert cited_ids(findings) <= set(state.store.records)  # nothing invented
    record = state.store.get(f"ctgov:{NCT}").data
    assert record["why_stopped"] == REASON and not record.get("has_results")
    assert all(c["agent"] == "researcher:trials" for c in state.tool_calls)


async def test_publications_researcher_returns_a_citable_answer():
    state = RunState(question="q")
    findings = await pipeline.run_researcher(state, Brief(lane="publications", brief=f"Find any journal article "
                                                          f"reporting results of {NCT} (latiglutenase, celiac disease)."), "p")
    assert findings.findings and cited_ids(findings) and cited_ids(findings) <= set(state.store.records)


@pytest.mark.skipif(not config.SEC_USER_AGENT, reason="needs SEC_USER_AGENT")
async def test_disclosures_researcher_returns_a_citable_answer():
    state = RunState(question="q")
    findings = await pipeline.run_researcher(state, Brief(lane="disclosures", brief=f"Find what the sponsor of {NCT} "
                                                          "(Entero Therapeutics, formerly First Wave BioPharma) told "
                                                          "investors about this latiglutenase trial."), "d")
    ids = cited_ids(findings)
    assert ids and ids <= set(state.store.records)
    assert any(i.startswith(("sec:", "cik:")) for i in ids)


async def test_researcher_starts_from_a_fresh_context():
    state = RunState(question="the Lead's own question, which a researcher must never see")
    await pipeline.run_researcher(state, Brief(lane="trials", brief=f"Status of {NCT}."), "fresh")
    first = state.first_contexts["fresh"]
    text = str(first)
    assert f"Status of {NCT}." in text and "must never see" not in text


# --- Writer and Checker ---

def store_with_the_trial() -> RunState:
    state = RunState(question=f"Why did {NCT} stop, and were its results posted?")
    row = db.trial_record(NCT)
    state.store.add(f"ctgov:{NCT}", row["title"], f"https://clinicaltrials.gov/study/{NCT}", row)
    return state


async def test_writer_cites_only_the_store_and_fills_every_section():
    state = store_with_the_trial()
    findings = [{"lane": "trials", "round": 1, "brief": "b", "gaps": [], "findings": [
        {"claim": f"{NCT} was terminated: {REASON}. No results are posted.", "evidence_ids": [f"ctgov:{NCT}"],
         "confidence": "high", "notes": ""}]}]
    report = await pipeline.run_writer(state, findings)
    claims = report.answer + report.evidence + report.differences
    assert report.answer and report.cant_tell
    assert {e for c in claims for e in c.citations} <= set(state.store.records)
    assert not any(re.search(r"—|–", c.text) for c in claims)


async def test_checker_rejects_a_planted_wrong_fact():
    state = store_with_the_trial()
    claims = [Claim(text=f"{NCT} was terminated because of a safety signal.", citations=[f"ctgov:{NCT}"]),
              Claim(text=f"{NCT} was terminated; the registry cites Covid-19 and enrollment challenges.",
                    citations=[f"ctgov:{NCT}"])]
    verdicts = {v.index: v for v in (await pipeline.run_checker(state, claims)).verdicts}
    assert verdicts[0].supported is False
    assert verdicts.get(1) is None or verdicts[1].supported is True
