"""The research pipeline: Lead (gate and plan) -> parallel Researchers -> Lead review (gaps) -> ... -> Writer -> Checker
-> Skeptic.

Five agent shapes:
  lead                      decides clarify / refuse / research, plans, and reviews findings for gaps
  researcher:<lane>         one shape, three lane configs (trials, disclosures, publications), fresh context each
  writer                    turns findings + evidence into the report, citing evidence ids only
  checker                   verifies each cited claim against the stored records; fixes or removes it
  skeptic                   reads the checked report like an editor: how strong the finding is, what ordinary
                            explanations the records can't rule out, and what to ask the sponsor

The loop is in code, not in the Lead's prompt, so the caps are guaranteed: MAX_RESEARCH_ROUNDS rounds,
RESEARCHER_MAX_TURNS per researcher, and a REQUEST_BUDGET_S wall clock for the whole request.
"""

import asyncio
import json
import re
import time
from typing import Literal

from agents import Agent, ItemHelpers, MaxTurnsExceeded, ModelSettings, Runner, set_tracing_disabled
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


class SkepticNotes(BaseModel):
    strength: Literal["strong", "moderate", "weak"]
    strength_reason: str = Field(description="One sentence naming the kinds of records the main finding rests on.")
    alternatives: list[str] = Field(default_factory=list, description="2 to 4 ordinary explanations the records can't rule out.")
    questions: list[str] = Field(default_factory=list, description="2 to 4 questions a reporter could put to the sponsor.")


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
skeptic = Agent(name="skeptic", instructions=prompt("skeptic"), model=model(config.CHECKER_MODEL), model_settings=SETTINGS,
                output_type=SkepticNotes)


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


def drop_unknown_ids(state: RunState, findings: Findings) -> Findings:
    """A researcher may only cite ids a tool put in the store. Unknown ids are removed before the Lead sees the
    findings; a finding left with no evidence is kept as low confidence and marked, so the Lead can send it back."""
    kept = []
    for f in findings.findings:
        known = [e for e in f.evidence_ids if e in state.store]
        dropped = [e for e in f.evidence_ids if e not in state.store]
        if not dropped:
            kept.append(f)
            continue
        note = f"cited ids no tool returned, removed: {', '.join(dropped)}"
        kept.append(Finding(claim=f.claim, evidence_ids=known, confidence=f.confidence if known else "low",
                            notes=f"{f.notes} ({note})".strip() if f.notes else note))
    return findings.model_copy(update={"findings": kept})


async def run_researcher(state: RunState, brief: Brief, key: str) -> Findings:
    """A fresh context: a new run whose input is only this brief. It never sees the Lead's or another researcher's messages."""
    agent = researcher(brief.lane)
    hooks = TraceHooks(state, agent.name, context_key=key)
    try:
        result = await Runner.run(agent, brief.brief, context=state, hooks=hooks, max_turns=config.RESEARCHER_MAX_TURNS)
        return drop_unknown_ids(state, result.final_output)
    except MaxTurnsExceeded as e:
        # Like the Lead: report now, with no tools, from its own conversation (so quotes still come from real excerpts).
        if e.run_data is not None:
            history = ItemHelpers.input_to_new_input_list(e.run_data.input)
            history += [item.to_input_item() for item in e.run_data.new_items]
            history.append({"role": "user", "content": "Turn cap reached. No more tool calls. Report your findings and gaps now, "
                                                       "from the tool results above only."})
            try:
                result = await Runner.run(agent.clone(tools=[]), history, context=state, hooks=hooks, max_turns=2)
                state.notes.append(f"{agent.name} hit its {config.RESEARCHER_MAX_TURNS}-turn cap and reported from what it had found.")
                return drop_unknown_ids(state, result.final_output)
            except MaxTurnsExceeded:
                pass
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


def timeline_text_problems(state: RunState, text: str) -> list[str]:
    """The Writer's timeline text cites nothing, so check it against every record in the store (plus each
    trial's derived dates, such as results_due_date): every date must be in one, and no overreaching words."""
    records = [r.as_dict() for r in state.store.records.values()]
    for r in list(state.store.records.values()):
        nct = r.evidence_id.split(":", 1)[1] if r.evidence_id.startswith("ctgov:") else ""
        if re.fullmatch(r"NCT\d{8}", nct) and db.DB_PATH.exists():
            row = db.trial_record(nct)
            if row:
                records.append({"title": "", "data": row})
    return citecheck.check_claim(text, records)


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
            unknown += sum(1 for e in claim.citations if e not in state.store)  # a repeated id is not unknown
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
            result = await asyncio.wait_for(run_checker(state, all_claims, rule_problems=rule_problems),
                                            timeout=max(MIN_STEP_S, state.remaining()))
            verdicts = {v.index: v for v in result.verdicts if 0 <= v.index < len(flat)}
        except asyncio.TimeoutError:
            model_ok = False
            state.notes.append("The Citation Checker model pass hit the time budget; the evidence-id and rule checks ran.")
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
    timeline_text = report.timeline_text
    timeline_problems = timeline_text_problems(state, timeline_text) if timeline_text.strip() else []
    if timeline_problems:
        # The text is regenerated from the records when the report is rendered.
        timeline_text = ""
        decisions.append({"section": "timeline", "claim": report.timeline_text, "action": "removed", "by": "rules",
                          "reason": "; ".join(timeline_problems)})
    before = sum(len(c) for c in (report.answer, report.evidence, report.differences))
    removed = before - sum(len(c) for c in final.values())
    stats = {"citations_checked": checked, "unknown_ids_dropped": unknown, "claims_fixed": fixed, "removed": removed,
             "rule_flags": flagged_by_rules, "model_pass": model_ok, "timeline_replaced": bool(timeline_problems),
             "decisions": decisions}
    state.record_call("checker", "check_citations", {"claims": before, "citations": checked},
                      f"citations_checked: {checked}, removed: {removed} (fixed {fixed}, rule flags {flagged_by_rules}, "
                      f"unknown ids dropped {unknown}"
                      + (", timeline text replaced" if timeline_problems else "") + ")")
    return report.model_copy(update={**final, "timeline_text": timeline_text}), stats


def _skeptic_input(state: RunState, report: WriterReport) -> str:
    cited = list(dict.fromkeys(e for claims in (report.answer, report.evidence, report.differences) for c in claims for e in c.citations))
    body = {"question": state.question,
            "report": {"answer": [c.text for c in report.answer], "evidence": [c.text for c in report.evidence],
                       "differences": [c.text for c in report.differences], "cant_tell": report.cant_tell}}
    return f"{json.dumps(body, default=str)}\n\nCited evidence records:\n{state.store.compact(cited[:40])}"


async def run_skeptic(state: RunState, report: WriterReport) -> SkepticNotes:
    result = await Runner.run(skeptic, _skeptic_input(state, report)[:100_000], context=state,
                              hooks=TraceHooks(state, "skeptic"), max_turns=2)
    return result.final_output


def screen_skeptic(state: RunState, notes: SkepticNotes) -> tuple[SkepticNotes, list[dict]]:
    """The Skeptic cites nothing, so every sentence it writes is held to the Checker's rules against the whole
    evidence store: no date or quote that isn't in a record, no overreaching word. A failing sentence is dropped."""
    records = [r.as_dict() for r in state.store.records.values()]
    dropped = []

    def keep(lines: list[str], kind: str) -> list[str]:
        kept = []
        for line in lines[:4]:
            problems = citecheck.check_claim(line, records)
            if problems:
                dropped.append({"kind": kind, "text": line, "reason": "; ".join(problems)})
            elif line.strip():
                kept.append(line.strip())
        return kept

    reason = notes.strength_reason if not citecheck.check_claim(notes.strength_reason, records) else ""
    return notes.model_copy(update={"alternatives": keep(notes.alternatives, "alternative"),
                                    "questions": keep(notes.questions, "question"), "strength_reason": reason}), dropped


SKEPTIC_MIN_S = 25.0  # the Skeptic is extra: it runs only when this much of the budget is left


async def skeptic_review(state: RunState, report: WriterReport) -> dict | None:
    """Run the Skeptic on a checked report with something in it. Returns its screened notes, or None when skipped."""
    if not (report.answer or report.evidence):
        return None
    if state.remaining() < SKEPTIC_MIN_S:
        state.notes.append("The Skeptic was skipped to stay inside the time limit.")
        return None
    state.emit({"type": "agent", "agent": "skeptic", "status": "start", "t": round(state.elapsed(), 2)})
    try:
        notes = await run_step(state, "Skeptic", lambda: run_skeptic(state, report), timeout=min(45.0, state.remaining()), attempts=1)
    except Exception as e:
        state.notes.append(f"The Skeptic did not finish ({type(e).__name__}); the report stands as checked.")
        state.emit({"type": "agent", "agent": "skeptic", "status": "end", "t": round(state.elapsed(), 2), "skipped": True})
        return None
    from ghost.style import no_dashes
    notes = notes.model_copy(update={"strength_reason": no_dashes(notes.strength_reason),
                                     "alternatives": [no_dashes(a) for a in notes.alternatives],
                                     "questions": [no_dashes(q) for q in notes.questions]})
    notes, dropped = screen_skeptic(state, notes)
    out = {**notes.model_dump(), "dropped": dropped}
    state.record_call("skeptic", "review_report", {"answer": len(report.answer), "differences": len(report.differences)},
                      f"strength: {notes.strength}; {len(notes.alternatives)} other explanations, {len(notes.questions)} questions "
                      f"for the sponsor; {len(dropped)} sentences dropped by the citation rules")
    state.emit({"type": "agent", "agent": "skeptic", "status": "end", "t": round(state.elapsed(), 2), "strength": notes.strength})
    return out


# --- Retries and time limits for the single-agent steps ---

MIN_STEP_S = 20.0  # never give a model step less than this, even when the budget is nearly gone
CHECKER_RESERVE_S = 25.0  # what the Writer leaves for the Checker


async def run_step(state: RunState, name: str, call, timeout: float, attempts: int = 2):
    """Run one model step with a time limit, and retry it once if it fails fast (a bad JSON output, a 5xx).
    A step that runs out of time is not retried: the budget is gone. The last error is raised."""
    for attempt in range(attempts):
        limit = max(MIN_STEP_S, min(timeout, state.remaining()))
        try:
            return await asyncio.wait_for(call(), timeout=limit)
        except asyncio.TimeoutError:
            raise
        except Exception as e:
            if attempt + 1 >= attempts or state.remaining() < MIN_STEP_S * 2:
                raise
            state.notes.append(f"The {name} failed once ({type(e).__name__}) and was retried.")


def fallback_report(findings: list[dict]) -> WriterReport:
    """When the Writer can't finish, report the researchers' own cited findings, so the user still gets
    checked evidence instead of an error. The Checker runs on these claims like any other."""
    claims = [Claim(text=f["claim"], citations=list(f["evidence_ids"]))
              for lane in findings for f in lane["findings"] if f["evidence_ids"]]
    return WriterReport(
        answer=claims[:1], evidence=claims[1:12],
        cant_tell=["The Writer did not finish, so these are the researchers' findings as they reported them, "
                   "without a written summary or a comparison across sources.",
                   "The registry, filings and papers only show what sponsors reported, not the real reason a trial stopped."],
        timeline_text="")


# --- The whole request ---

MAX_QUESTION_CHARS = 4000
EXAMPLE_QUESTIONS = [
    "Why did NCT04903327 stop, and were its results ever posted or published?",
    "Did Entero Therapeutics stop any phase 2 trials without posting results?",
    "Where does a sponsor's registry reason for stopping a trial differ from what it told investors?",
]


def question_problem(question: str) -> str | None:
    """Why a question can't be researched as sent (empty, or far too long), or None."""
    if not question or not question.strip():
        return "Ask about a drug, a sponsor, a condition or an NCT ID, and what you want to know about its stopped trials."
    if len(question) > MAX_QUESTION_CHARS:
        return f"That message is {len(question):,} characters. Please ask in under {MAX_QUESTION_CHARS:,}: name the drug, sponsor, condition or NCT ID."
    return None


async def investigate(question: str, emit=lambda event: None, budget_s: float | None = None) -> dict:
    """Answer one question. Returns {markdown, kind, report, sources, timeline, checker, trace, tool_calls}."""
    from ghost.report import clarification_markdown, render  # local: report imports this module's models

    state = RunState(question=question, emit=emit)
    problem = question_problem(question)
    if problem:
        # Nothing worth a model call: answer in the same shape, with what the tool can do.
        return {"kind": "refuse", "markdown": f"{problem}\n\nTry one of these:\n" + "\n".join(f"- {o}" for o in EXAMPLE_QUESTIONS),
                "options": EXAMPLE_QUESTIONS, "tool_calls": [], "trace": trace(state), "report": None, "sources": [], "timeline": []}
    if budget_s:
        state.budget_s = budget_s
    emit({"type": "agent", "agent": "lead", "status": "start", "t": 0})
    lead_limit = max(MIN_STEP_S, state.remaining() - config.WRITE_RESERVE_S - 30)
    try:
        plan = await run_step(state, "Lead", lambda: run_lead_plan(state), timeout=lead_limit)
    except asyncio.TimeoutError:
        raise RuntimeError(f"The Lead did not finish planning within {int(lead_limit)} s.") from None
    emit({"type": "agent", "agent": "lead", "status": "end", "t": round(state.elapsed(), 2), "decision": plan.decision})
    state.record_call("lead", "plan", {"question": question},
                      json.dumps({"decision": plan.decision, "plan": plan.plan, "lanes": [b.lane for b in plan.briefs]}))

    if plan.decision in ("clarify", "refuse"):
        return {"kind": plan.decision, "markdown": clarification_markdown(plan), "options": plan.options,
                "tool_calls": state.tool_calls, "trace": trace(state), "report": None, "sources": [], "timeline": []}

    findings = await research(state, plan)
    emit({"type": "agent", "agent": "writer", "status": "start", "t": round(state.elapsed(), 2)})
    try:
        report = await run_step(state, "Writer", lambda: run_writer(state, findings),
                                timeout=state.remaining() - CHECKER_RESERVE_S)
    except asyncio.TimeoutError:
        state.notes.append("The Writer hit the time budget, so the report lists the researchers' findings directly.")
        report = fallback_report(findings)
    except Exception as e:
        state.notes.append(f"The Writer failed ({type(e).__name__}), so the report lists the researchers' findings directly.")
        report = fallback_report(findings)
    state.record_call("writer", "write_report", {"findings": sum(len(f["findings"]) for f in findings), "evidence_records": len(state.store.records)},
                      f"{len(report.answer)} answer sentences, {len(report.evidence)} evidence claims, {len(report.differences)} differences")
    emit({"type": "agent", "agent": "writer", "status": "end", "t": round(state.elapsed(), 2)})
    emit({"type": "agent", "agent": "checker", "status": "start", "t": round(state.elapsed(), 2)})
    report, checker_stats = await check_citations(state, report)
    emit({"type": "agent", "agent": "checker", "status": "end", "t": round(state.elapsed(), 2), **checker_stats})
    skeptic_notes = await skeptic_review(state, report)
    rendered = render(state, report, checker_stats, skeptic=skeptic_notes)
    return {"kind": "report", **rendered, "checker": checker_stats, "skeptic": skeptic_notes, "tool_calls": state.tool_calls,
            "trace": trace(state), "findings": findings}


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
