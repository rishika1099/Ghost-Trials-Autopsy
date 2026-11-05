"""Every [n] in the report maps to a source, and every source's evidence_id exists in the evidence store.
Citations to ids that aren't in the store are dropped, and claims the Checker can't support are removed."""

import re

from ghost import pipeline
from ghost.pipeline import Claim, CheckerVerdicts, Verdict, WriterReport
from ghost.report import render
from ghost.state import RunState


def make_state() -> RunState:
    state = RunState(question="NCT01234567")
    state.store.add("ctgov:NCT01234567", "Trial A", "https://clinicaltrials.gov/study/NCT01234567",
                    {"nct_id": "NCT01234567", "overall_status": "TERMINATED", "why_stopped": "Sponsor decision", "has_results": False})
    state.store.add("sec:0001193125-21-000001", "Acme 8-K", "https://www.sec.gov/Archives/edgar/data/1/000119312521000001/a.htm",
                    {"accession": "0001193125-21-000001", "form": "8-K", "filed_date": "2021-03-01", "excerpts": ["discontinue due to safety"]})
    return state


async def test_citations_map_to_sources(monkeypatch):
    state = make_state()
    report = WriterReport(
        answer=[Claim(text="The trial was terminated.", citations=["ctgov:NCT01234567"]),
                Claim(text="A claim citing a record nobody fetched.", citations=["pubmed:99999999"])],
        evidence=[Claim(text="The 8-K says safety.", citations=["sec:0001193125-21-000001", "ctgov:NCT01234567"]),
                  Claim(text="The 8-K was filed in 2019.", citations=["sec:0001193125-21-000001"])],
        differences=[Claim(text="The registry says sponsor decision; the 8-K says safety.", citations=["ctgov:NCT01234567", "sec:0001193125-21-000001"])],
        cant_tell=["We only know the stated reason."], timeline_text="Terminated.")

    async def checker(state, claims, **kwargs):
        # Claim 2 (index 2 after the unknown-id claim is dropped) has a wrong year: remove it.
        return CheckerVerdicts(verdicts=[Verdict(index=2, supported=False, fixed_text=None, reason="filed 2021, not 2019")])

    monkeypatch.setattr(pipeline, "run_checker", checker)
    checked, stats = await pipeline.check_citations(state, report)
    assert stats["unknown_ids_dropped"] == 1 and stats["removed"] == 2
    assert all("2019" not in c.text for c in checked.evidence)
    assert any(c["name"] == "check_citations" and c["agent"] == "checker" for c in state.tool_calls)

    out = render(state, checked, stats)
    numbers = {int(n) for n in re.findall(r"\[(\d+)\]", out["markdown"].split("## Sources")[0])}
    sources = {s["n"]: s for s in out["sources"]}
    assert numbers and numbers <= set(sources), (numbers, sources)
    for source in out["sources"]:
        assert source["evidence_id"] in state.store
        assert source["url"] == state.store.get(source["evidence_id"]).source_url
    assert "pubmed:99999999" not in out["markdown"]
    assert "citations_checked: 7, removed: 2" in out["markdown"]


async def test_checker_fix_replaces_text(monkeypatch):
    state = make_state()
    report = WriterReport(answer=[Claim(text="The company hid the safety problem.", citations=["sec:0001193125-21-000001"])],
                          evidence=[], cant_tell=["x"], timeline_text="")

    async def checker(state, claims, **kwargs):
        return CheckerVerdicts(verdicts=[Verdict(index=0, supported=False, fixed_text="The 8-K mentions discontinuing due to safety.")])

    monkeypatch.setattr(pipeline, "run_checker", checker)
    checked, stats = await pipeline.check_citations(state, report)
    assert checked.answer[0].text == "The 8-K mentions discontinuing due to safety." and stats["claims_fixed"] == 1


async def test_rules_catch_errors_even_when_the_model_pass_fails(monkeypatch):
    state = make_state()
    report = WriterReport(answer=[Claim(text="The 8-K says the drug was stopped \"because of a safety signal in patients\".",
                                        citations=["sec:0001193125-21-000001"]),
                                  Claim(text="The 8-K was filed on 2021-04-01.", citations=["sec:0001193125-21-000001"]),
                                  Claim(text="The sponsor concealed the safety problem.", citations=["sec:0001193125-21-000001"]),
                                  Claim(text="The 8-K was filed on 2021-03-01.", citations=["sec:0001193125-21-000001"])],
                          evidence=[], cant_tell=["x"], timeline_text="")

    async def broken(state, claims, **kwargs):
        raise TimeoutError("model down")

    monkeypatch.setattr(pipeline, "run_checker", broken)
    checked, stats = await pipeline.check_citations(state, report)
    assert [c.text for c in checked.answer] == ["The 8-K was filed on 2021-03-01."]
    assert stats["removed"] == 3 and stats["rule_flags"] == 3 and stats["model_pass"] is False
    assert [d["action"] for d in stats["decisions"]] == ["removed", "removed", "removed", "kept"]


async def test_a_fix_that_still_overreaches_is_rejected(monkeypatch):
    state = make_state()
    report = WriterReport(answer=[Claim(text="The company hid the safety problem.", citations=["sec:0001193125-21-000001"])],
                          evidence=[], cant_tell=["x"], timeline_text="")

    async def checker(state, claims, **kwargs):
        assert kwargs["rule_problems"][0], "the rule problems reach the model as hints"
        return CheckerVerdicts(verdicts=[Verdict(index=0, supported=False, fixed_text="The company concealed a safety problem.")])

    monkeypatch.setattr(pipeline, "run_checker", checker)
    checked, stats = await pipeline.check_citations(state, report)
    assert checked.answer == [] and stats["removed"] == 1 and stats["decisions"][0]["by"] == "rules"


async def test_rule_flag_overrides_a_model_that_says_supported(monkeypatch):
    state = make_state()
    report = WriterReport(answer=[Claim(text="The 8-K was filed on 2019-03-01.", citations=["sec:0001193125-21-000001"])],
                          evidence=[], cant_tell=["x"], timeline_text="")

    async def lenient(state, claims, **kwargs):
        return CheckerVerdicts(verdicts=[Verdict(index=0, supported=True)])

    monkeypatch.setattr(pipeline, "run_checker", lenient)
    checked, stats = await pipeline.check_citations(state, report)
    assert checked.answer == [] and "date 2019-03-01" in stats["decisions"][0]["reason"]
