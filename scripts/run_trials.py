"""Run only the trials researcher on 10 briefs the samples don't cover, and check its facts against the records.

    uv run python scripts/run_trials.py            # all 10
    uv run python scripts/run_trials.py t04 t07    # some of them

Checks per finding: every cited evidence_id exists; every date (YYYY-MM-DD) in a claim that cites a trial record
appears in that record; every "quoted phrase" appears in a cited record; a withdrawn trial is never called late or
overdue. Outputs go to runs/trials_<id>.json and a summary is printed.
"""

import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ghost.config import ROOT  # noqa: E402
from ghost.pipeline import Brief, run_researcher  # noqa: E402
from ghost.state import RunState  # noqa: E402

BRIEFS = {
    "t01_safety": "Trial NCT03068754 (Mallinckrodt). Why did it stop, what category is the stated reason, and were results posted on time?",
    "t02_efficacy": "Trial NCT03738423 (Regeneron, phase 2). Status, stated reason for stopping quoted exactly, enrollment, and when results were posted relative to the approximate due date.",
    "t03_enrollment": "Trial NCT03433703 (Eisai, phase 2). Why did it stop and how many people were enrolled? Were results posted?",
    "t04_withdrawn": "Trial NCT02406508 (Delcath Systems, phase 2). What happened to it, how many people enrolled, and does it owe results?",
    "t05_blank_reason": "Trial NCT02522598 (Vivozon, phase 2). What is its status and stated reason, and were results ever posted?",
    "t06_suspended": "Trial NCT01010373 (BioMAS). What is its status and stated reason? Put the trial in context with snapshot base rates.",
    "t07_sponsor": "Sponsor Ultragenyx Pharmaceutical. List its stopped (terminated, withdrawn or suspended) trials in the snapshot with phase, status, stated reason and whether results were posted.",
    "t08_condition": "Industry phase 2 Alzheimer's disease trials that stopped (terminated, withdrawn or suspended) in the snapshot: how many, and how do they break down by why_stopped_category?",
    "t09_fda": "Trial NCT03684694 (ADC Therapeutics). Why did it stop, and was the drug it tested (loncastuximab tesirine) ever approved by the FDA, and when?",
    "t10_out_of_scope": "Trial NCT05824559 (MEI Pharma). Why did it stop and were results posted? It may be outside the snapshot scope.",
}
DATE = re.compile(r"\b(19|20)\d{2}-\d{2}-\d{2}\b")
QUOTE = re.compile(r"[\"“]([^\"”]{8,})[\"”]")


def flat(record) -> str:
    return json.dumps(record.as_dict(), default=str)


def check(state: RunState, findings: dict) -> list[str]:
    problems = []
    for f in findings["findings"]:
        records = [state.store.get(e) for e in f["evidence_ids"]]
        for e, r in zip(f["evidence_ids"], records):
            if r is None:
                problems.append(f"unknown evidence id {e}")
        records = [r for r in records if r]
        pool = " ".join(flat(r) for r in records)
        trial_pool = " ".join(flat(r) for r in records if r.evidence_id.startswith(("ctgov:", "sql:")))
        if trial_pool:
            for m in DATE.finditer(f["claim"]):
                if m.group(0) not in trial_pool:
                    problems.append(f"date {m.group(0)} not in cited trial records: {f['claim'][:120]}")
        for q in QUOTE.findall(f["claim"]):
            if re.sub(r"\s+", " ", q) not in re.sub(r"\s+", " ", pool):
                problems.append(f"quote not in cited records: \"{q[:80]}\"")
        withdrawn = any(r.data.get("overall_status") == "WITHDRAWN" for r in records)
        if withdrawn and re.search(r"\b(late|overdue)\b", f["claim"], re.I) and not re.search(r"\bnot\b", f["claim"], re.I):
            problems.append(f"withdrawn trial called late: {f['claim'][:120]}")
    return problems


async def main() -> None:
    wanted = set(sys.argv[1:])
    total = 0
    for key, brief in BRIEFS.items():
        if wanted and not any(key.startswith(w) for w in wanted):
            continue
        state = RunState(brief)
        findings = (await run_researcher(state, Brief(lane="trials", brief=brief), f"researcher:trials#{key}")).model_dump()
        problems = check(state, findings)
        total += len(problems)
        calls = [{"name": c["name"], "args": c["args"], "result": c["result"]} for c in state.tool_calls]
        out = {"brief": brief, "findings": findings, "problems": problems, "tool_calls": calls}
        (ROOT / "runs" / f"trials_{key}.json").write_text(json.dumps(out, indent=2, default=str))
        print(f"## {key}: {len(findings['findings'])} findings, {len(calls)} tool calls, {len(problems)} problems")
        for f in findings["findings"]:
            print(f"- {f['claim']} {f['evidence_ids']} ({f['confidence']})")
        for p in problems:
            print(f"  PROBLEM: {p}")
        print(f"  gaps: {findings['gaps']}\n", flush=True)
    print(f"total problems: {total}")


if __name__ == "__main__":
    asyncio.run(main())
