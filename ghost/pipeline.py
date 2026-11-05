"""The research pipeline: Lead (gate and plan) -> parallel Researchers -> Lead review (gaps) -> ... -> Writer -> Checker.

Four agent shapes:
  lead                      decides clarify / refuse / research, plans, and reviews findings for gaps
  researcher:<lane>         one shape, three lane configs (trials, disclosures, publications), fresh context each
  writer                    turns findings + evidence into the report, citing evidence ids only
  checker                   verifies each cited claim against the stored records; fixes or removes it

The loop is in code, not in the Lead's prompt, so the caps are guaranteed: MAX_RESEARCH_ROUNDS rounds,
RESEARCHER_MAX_TURNS per researcher, and a REQUEST_BUDGET_S wall clock for the whole request.
"""

import asyncio
import json
import time
from typing import Literal

from agents import Agent, MaxTurnsExceeded, ModelSettings, Runner, set_tracing_disabled
from agents.extensions.models.litellm_model import LitellmModel
from pydantic import BaseModel, Field

from ghost import citecheck, config, db
from ghost.hooks import TraceHooks
from ghost.state import RunState
from ghost.tools import DISCLOSURES_TOOLS, LEAD_TOOLS, PUBLICATIONS_TOOLS, TRIALS_TOOLS

# Traces upload to OpenAI by default, which needs an OpenAI key. We're on Gemini.
set_tracing_disabled(True)

Lane = Literal["trials", "disclosures", "publications"]
LANES: tuple[str, ...] = ("trials", "disclosures", "publications")


def prompt(name: str) -> str:
    return (config.PROMPTS_DIR / f"{name}.md").read_text()


def model(name: str) -> LitellmModel:
    # LiteLLM routes the call to Gemini. api_key is unused: Vertex AI uses gcloud / service account credentials.
    return LitellmModel(model=name, api_key="unused")


# A stalled model call would hang the page: give up after 90 s, and retry twice.
SETTINGS = ModelSettings(extra_args={**config.VERTEX_ARGS, "timeout": 90, "num_retries": 2})


# --- Structured outputs ---


class Brief(BaseModel):
    lane: Lane
    brief: str = Field(description="Self-contained task: NCT IDs, sponsor, drug names, date window, what to find.")


class LeadPlan(BaseModel):
    decision: Literal["clarify", "refuse", "research"]
    message: str = Field(description="For clarify/refuse: the question or refusal shown to the user. For research: empty.")
    options: list[str] = Field(default_factory=list, description="For clarify/refuse: 2 to 4 concrete rewrites.")
    plan: str = Field(default="", description="For research: 2 to 4 sentences.")
    briefs: list[Brief] = Field(default_factory=list, description="For research: one per relevant lane.")


class Gap(BaseModel):
    lane: Lane
    description: str = Field(description="What is missing, e.g. 'sponsor matched to CIK but no 8-K in the window'.")
    brief: str = Field(description="Self-contained brief for the researcher who will close it.")


class LeadReview(BaseModel):
    done: bool
    gaps: list[Gap] = Field(default_factory=list)


class Finding(BaseModel):
    claim: str
    evidence_ids: list[str]
    confidence: Literal["high", "medium", "low"]
    notes: str = ""


class Findings(BaseModel):
    findings: list[Finding]
    gaps: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    text: str
    citations: list[str] = Field(description="Evidence ids exactly as given, e.g. ctgov:NCT01234567.")


class WriterReport(BaseModel):
    answer: list[Claim]
    evidence: list[Claim]
    differences: list[Claim] = Field(default_factory=list)
    cant_tell: list[str]
    timeline_text: str


class Verdict(BaseModel):
    index: int
    supported: bool
    fixed_text: str | None = None
    reason: str = ""


class CheckerVerdicts(BaseModel):
    verdicts: list[Verdict]


# --- Agents ---

lead = Agent(name="lead", instructions=prompt("lead"), model=model(config.LEAD_MODEL), model_settings=SETTINGS,
             tools=LEAD_TOOLS, output_type=LeadPlan)
lead_reviewer = Agent(name="lead", instructions=prompt("lead_review"), model=model(config.LEAD_MODEL),
                      model_settings=SETTINGS, output_type=LeadReview)
LANE_TOOLS = {"trials": TRIALS_TOOLS, "disclosures": DISCLOSURES_TOOLS, "publications": PUBLICATIONS_TOOLS}


def researcher(lane: str) -> Agent:
    """One shape, three configs: the same instructions plus a lane section and the lane's tools."""
    return Agent(name=f"researcher:{lane}", instructions=prompt("researcher") + "\n\n" + prompt(f"lane_{lane}"),
                 model=model(config.RESEARCHER_MODEL), model_settings=SETTINGS, tools=LANE_TOOLS[lane], output_type=Findings)


writer = Agent(name="writer", instructions=prompt("writer"), model=model(config.WRITER_MODEL), model_settings=SETTINGS,
               output_type=WriterReport)
checker = Agent(name="checker", instructions=prompt("checker"), model=model(config.CHECKER_MODEL), model_settings=SETTINGS,
                output_type=CheckerVerdicts)


# --- Steps. Each is a module-level function so tests can stub it. ---


async def run_lead_plan(state: RunState) -> LeadPlan:
    try:
        result = await Runner.run(lead, state.question, context=state, hooks=TraceHooks(state, "lead"), max_turns=config.LEAD_MAX_TURNS)
        return result.final_output
    except MaxTurnsExceeded:
        # The Lead kept looking things up. Plan now, with no tools, from what its lookups found.
        state.notes.append("The Lead hit its lookup cap and planned from what it had found.")
        lookups = "\n".join(f"- {c['name']}({json.dumps(c['args'], default=str)[:300]}) -> {c['result']}"
                            for c in state.tool_calls if c["agent"] == "lead")
        planner = lead.clone(tools=[])
        prompt_text = f"{state.question}\n\nYour lookups so far:\n{lookups or '- none'}\n\nDecide and plan now. No more lookups."
        result = await Runner.run(planner, prompt_text, context=state, hooks=TraceHooks(state, "lead"), max_turns=2)
        return result.final_output


async def run_lead_review(state: RunState, plan: LeadPlan, findings: list[dict]) -> LeadReview:
    message = json.dumps({"question": state.question, "plan": plan.plan, "round": state.rounds,
                          "max_rounds": config.MAX_RESEARCH_ROUNDS, "findings": findings}, default=str)
    result = await Runner.run(lead_reviewer, message, context=state, hooks=TraceHooks(state, "lead"), max_turns=2)
    return result.final_output


async def run_researcher(state: RunState, brief: Brief, key: str) -> Findings:
    """A fresh context: a new run whose input is only this brief. It never sees the Lead's or another researcher's messages."""
    agent = researcher(brief.lane)
    hooks = TraceHooks(state, agent.name, context_key=key)
    try:
        result = await Runner.run(agent, brief.brief, context=state, hooks=hooks, max_turns=config.RESEARCHER_MAX_TURNS)
        return result.final_output
    except MaxTurnsExceeded:
        seen = sorted(set(hooks.evidence_seen))
        return Findings(findings=[Finding(claim=f"Ran out of turns. Records gathered: {', '.join(seen) or 'none'}.",
                                          evidence_ids=seen, confidence="low")],
                        gaps=[f"Researcher hit the {config.RESEARCHER_MAX_TURNS}-turn cap before finishing: {brief.brief[:200]}"])


async def dispatch_researchers(state: RunState, briefs: list[Brief]) -> list[dict]:
    """The fan-out: every brief runs at once with asyncio.gather, each in a fresh context. Logs start and end times."""
    round_no = state.rounds
    timeout = max(20.0, state.remaining() - config.WRITE_RESERVE_S)

    async def one(i: int, brief: Brief) -> dict:
        key = f"researcher:{brief.lane}#r{round_no}.{i}"
        timing = {"agent": f"researcher:{brief.lane}", "key": key, "round": round_no, "start": round(state.elapsed(), 3)}
        state.emit({"type": "agent", "agent": timing["agent"], "key": key, "status": "start", "round": round_no, "t": timing["start"], "brief": brief.brief})
        try:
            result = await asyncio.wait_for(run_researcher(state, brief, key), timeout=timeout)
            output = result.model_dump()
        except asyncio.TimeoutError:
            output = {"findings": [], "gaps": [f"Stopped at the time budget before finishing: {brief.brief[:200]}"]}
            state.notes.append(f"A {brief.lane} researcher hit the time budget in round {round_no}.")
        except Exception as e:  # one researcher failing should not sink the report
            output = {"findings": [], "gaps": [f"Researcher failed: {type(e).__name__}: {str(e)[:200]}"]}
        timing["end"] = round(state.elapsed(), 3)
        state.timings.append(timing)
        state.emit({"type": "agent", "agent": timing["agent"], "key": key, "status": "end", "round": round_no, "t": timing["end"],
                    "findings": len(output["findings"])})
        return {"lane": brief.lane, "round": round_no, "brief": brief.brief, **output}

    return await asyncio.gather(*(one(i, b) for i, b in enumerate(briefs)))


def _summarize_briefs(briefs: list[Brief]) -> list[dict]:
    return [{"lane": b.lane, "brief": b.brief[:300]} for b in briefs]


async def research(state: RunState, plan: LeadPlan) -> list[dict]:
    """Rounds of fan-out and review, until the Lead finds no gap worth chasing, the round cap, or the budget."""
    findings: list[dict] = []
    briefs = plan.briefs or [Brief(lane=lane, brief=state.question) for lane in LANES]
    while True:
        state.rounds += 1
        state.emit({"type": "round", "round": state.rounds})
        round_findings = await dispatch_researchers(state, briefs)
        findings.extend(round_findings)
        timings = [t for t in state.timings if t["round"] == state.rounds]
        state.record_call("lead", "dispatch_researchers", {"round": state.rounds, "briefs": _summarize_briefs(briefs)},
                          f"{len(briefs)} researchers in parallel, {sum(len(f['findings']) for f in round_findings)} findings; "
                          + ", ".join(f"{t['agent']} {t['start']}s-{t['end']}s" for t in timings))
        if state.rounds >= config.MAX_RESEARCH_ROUNDS:
            state.notes.append(f"Stopped at the cap of {config.MAX_RESEARCH_ROUNDS} research rounds.")
            break
        if state.remaining() < config.WRITE_RESERVE_S + 30:
            state.notes.append(f"Stopped after round {state.rounds} to stay inside the {int(state.budget_s)} s time budget.")
            break
        try:
            review = await run_lead_review(state, plan, findings)
        except Exception as e:
            state.notes.append(f"Lead review failed ({type(e).__name__}); wrote with the findings so far.")
            break
        state.record_call("lead", "review_findings", {"round": state.rounds},
                          json.dumps({"done": review.done, "gaps": [g.model_dump(include={"lane", "description"}) for g in review.gaps]}))
        if review.done or not review.gaps:
            break
        briefs = [Brief(lane=g.lane, brief=f"{g.brief}\n\n(Gap to close: {g.description})") for g in review.gaps[:3]]
    return findings


def _writer_input(state: RunState, findings: list[dict]) -> str:
    cited = [i for f in findings for finding in f["findings"] for i in finding["evidence_ids"]]
    ids = list(dict.fromkeys([i for i in cited if i in state.store] + list(state.store.records)))[:70]
    return (f"Question: {state.question}\n\nSnapshot date: {db.snapshot_date() or 'unknown'}\n"
            f"Research notes: {'; '.join(state.notes) or 'none'}\n\n"
            f"Findings:\n{json.dumps(findings, default=str)}\n\nEvidence records (cite only these ids):\n{state.store.compact(ids)}")


async def run_writer(state: RunState, findings: list[dict]) -> WriterReport:
    result = await Runner.run(writer, _writer_input(state, findings), context=state, hooks=TraceHooks(state, "writer"),
                              max_turns=config.WRITER_MAX_TURNS)
    return result.final_output


async def run_checker(state: RunState, claims: list[Claim], rule_problems: dict[int, list[str]] | None = None) -> CheckerVerdicts:
    rule_problems = rule_problems or {}
    items = [{"index": i, "claim": c.text, "rule_problems": rule_problems.get(i, []),
              "evidence": [state.store.get(e).as_dict() for e in c.citations if e in state.store]}
             for i, c in enumerate(claims)]
    text = json.dumps(items, default=str)
    result = await Runner.run(checker, text[:120_000], context=state, hooks=TraceHooks(state, "checker"), max_turns=config.CHECKER_MAX_TURNS)
    return result.final_output


async def check_citations(state: RunState, report: WriterReport) -> tuple[WriterReport, dict]:
    """Three passes. 1: every citation must name a record in the store. 2: deterministic rules (ghost/citecheck.py):
    quotes must be in the cited records, dates must be in them, and no overreaching words. 3: the Checker model
    compares each claim to its records, with the rule problems as hints. A claim with any problem is replaced by the
    model's fixed_text only if that text passes the rules too; otherwise it is removed. Returns the cleaned report and
    the counts for the trace, with one decision per claim."""
    sections = {"answer": report.answer, "evidence": report.evidence, "differences": report.differences}
    checked = sum(len(c.citations) for claims in sections.values() for c in claims)
    unknown = 0
    decisions = []
    for name, claims in sections.items():
        kept = []
        for claim in claims:
            valid = [e for e in dict.fromkeys(claim.citations) if e in state.store]
            unknown += len(claim.citations) - len(valid)
            if valid:
                kept.append(Claim(text=claim.text, citations=valid))
            else:
                decisions.append({"section": name, "claim": claim.text, "action": "removed", "by": "evidence_ids",
                                  "reason": f"cites no record in the store: {', '.join(claim.citations) or 'nothing'}"})
        sections[name] = kept

    flat = [(name, i) for name, claims in sections.items() for i in range(len(claims))]
    all_claims = [sections[name][i] for name, i in flat]

    def records(claim: Claim) -> list[dict]:
        return [state.store.get(e).as_dict() for e in claim.citations if e in state.store]

    rule_problems = {n: citecheck.check_claim(c.text, records(c)) for n, c in enumerate(all_claims)}
    verdicts, model_ok = {}, True
    if all_claims:
        try:
            result = await run_checker(state, all_claims, rule_problems=rule_problems)
            verdicts = {v.index: v for v in result.verdicts if 0 <= v.index < len(flat)}
        except Exception as e:
            model_ok = False
            state.notes.append(f"Citation Checker model pass failed ({type(e).__name__}); the evidence-id and rule checks ran.")
    fixed, flagged_by_rules, removed_ids = 0, 0, set()
    for n, (name, i) in enumerate(flat):
        claim, verdict = sections[name][i], verdicts.get(n)
        problems = list(rule_problems[n])
        flagged_by_rules += bool(problems)
        if verdict is not None and not verdict.supported:
            problems.append(f"model: {verdict.reason or 'not supported by the cited records'}")
        if not problems:
            decisions.append({"section": name, "claim": claim.text, "action": "kept", "by": "rules+model" if model_ok else "rules"})
            continue
        candidate = (verdict.fixed_text or "").strip() if verdict is not None else ""
        still_wrong = citecheck.check_claim(candidate, records(claim)) if candidate else ["no fix offered"]
        if candidate and not still_wrong:
            sections[name][i] = Claim(text=candidate, citations=claim.citations)
            fixed += 1
            decisions.append({"section": name, "claim": claim.text, "action": "fixed", "fixed_text": candidate,
                              "by": "rules+model" if rule_problems[n] else "model", "reason": "; ".join(problems)})
        else:
            removed_ids.add(n)
            decisions.append({"section": name, "claim": claim.text, "action": "removed",
                              "by": "rules" if rule_problems[n] else "model", "reason": "; ".join(problems)})
    final = {name: [] for name in sections}
    for n, (name, i) in enumerate(flat):
        if n not in removed_ids:
            final[name].append(sections[name][i])
    before = sum(len(c) for c in (report.answer, report.evidence, report.differences))
    removed = before - sum(len(c) for c in final.values())
    stats = {"citations_checked": checked, "unknown_ids_dropped": unknown, "claims_fixed": fixed, "removed": removed,
             "rule_flags": flagged_by_rules, "model_pass": model_ok, "decisions": decisions}
    state.record_call("checker", "check_citations", {"claims": before, "citations": checked},
                      f"citations_checked: {checked}, removed: {removed} (fixed {fixed}, rule flags {flagged_by_rules}, "
                      f"unknown ids dropped {unknown})")
    return report.model_copy(update=final), stats


# --- The whole request ---


async def investigate(question: str, emit=lambda event: None, budget_s: float | None = None) -> dict:
    """Answer one question. Returns {markdown, kind, report, sources, timeline, checker, trace, tool_calls}."""
    from ghost.report import clarification_markdown, render  # local: report imports this module's models

    state = RunState(question=question, emit=emit)
    if budget_s:
        state.budget_s = budget_s
    emit({"type": "agent", "agent": "lead", "status": "start", "t": 0})
    plan = await run_lead_plan(state)
    emit({"type": "agent", "agent": "lead", "status": "end", "t": round(state.elapsed(), 2), "decision": plan.decision})
    state.record_call("lead", "plan", {"question": question},
                      json.dumps({"decision": plan.decision, "plan": plan.plan, "lanes": [b.lane for b in plan.briefs]}))

    if plan.decision in ("clarify", "refuse"):
        return {"kind": plan.decision, "markdown": clarification_markdown(plan), "options": plan.options,
                "tool_calls": state.tool_calls, "trace": trace(state), "report": None, "sources": [], "timeline": []}

    findings = await research(state, plan)
    emit({"type": "agent", "agent": "writer", "status": "start", "t": round(state.elapsed(), 2)})
    report = await run_writer(state, findings)
    state.record_call("writer", "write_report", {"findings": sum(len(f["findings"]) for f in findings), "evidence_records": len(state.store.records)},
                      f"{len(report.answer)} answer sentences, {len(report.evidence)} evidence claims, {len(report.differences)} differences")
    emit({"type": "agent", "agent": "writer", "status": "end", "t": round(state.elapsed(), 2)})
    emit({"type": "agent", "agent": "checker", "status": "start", "t": round(state.elapsed(), 2)})
    report, checker_stats = await check_citations(state, report)
    emit({"type": "agent", "agent": "checker", "status": "end", "t": round(state.elapsed(), 2), **checker_stats})
    rendered = render(state, report, checker_stats)
    return {"kind": "report", **rendered, "checker": checker_stats, "tool_calls": state.tool_calls, "trace": trace(state),
            "findings": findings}


def trace(state: RunState) -> dict:
    return {"rounds": state.rounds, "max_rounds": config.MAX_RESEARCH_ROUNDS, "timings": state.timings,
            "elapsed_s": round(state.elapsed(), 2), "notes": state.notes, "first_contexts": state.first_contexts}


if __name__ == "__main__":
    import sys

    question = " ".join(sys.argv[1:]) or "Why do trials fail?"
    started = time.monotonic()
    out = asyncio.run(investigate(question, emit=lambda e: print(json.dumps(e, default=str)[:300], flush=True)))
    print(out["markdown"])
    print(f"\n{time.monotonic() - started:.1f}s")
