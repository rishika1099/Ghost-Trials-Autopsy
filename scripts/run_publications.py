"""Run only the publications researcher on the three sample queries, and check what it says about publication.

    uv run python scripts/run_publications.py          # s1, s2, s3
    uv run python scripts/run_publications.py s2       # one of them

Each brief is what the Lead would send for that sample. Checks per run:
- every cited evidence_id exists;
- for each trial find_publications returned with no results_candidate, a finding says "no results publication
  found" and cites that trial's "No results publication found" record (pubmed:none:<nct>);
- no finding cites a mention_only or background article for a claim that the trial was published or reported results.
Outputs go to runs/publications_<id>.json and a summary is printed.
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
    "s1_discrepancy": "Publications for vTv Therapeutics trial NCT03980730 (Elevage, azeliragon in mild Alzheimer's disease with "
                      "impaired glucose tolerance, phase 2, terminated 'for business reasons'; primary completion 2020-12-01). "
                      "Was a paper reporting this trial's results ever published? Give PMID, journal and date if so.",
    "s2_never_posted": "Publications for Sorrento Therapeutics trial NCT04903327 (COVI-MSC, phase 2, terminated for slow enrollment; "
                       "primary completion 2022-08-29; results never posted to the registry). Was a paper reporting its results "
                       "ever published?",
    "s3_sponsor": "Publications for Entero Therapeutics (formerly First Wave BioPharma and AzurRx BioPharma) stopped phase 2 "
                  "trials: NCT04858425 (niclosamide), NCT04839575 and NCT04243551 (latiglutenase), NCT04542434 and NCT04436458. "
                  "For each, was a paper reporting its results published?",
}
PUBLISHED = re.compile(r"\b(published|reports? (the |its )?results|results (paper|publication))\b", re.I)
NEGATED = re.compile(r"\b(no|not|never|none|only mention|without)\b", re.I)


def check(state: RunState, findings: dict) -> list[str]:
    problems = []
    pubs = state.store.records
    weak = {e for e, r in pubs.items() if e.startswith("pubmed:") and r.data.get("link_strength") in ("mention_only", "background")}
    none_records = {e: r.data.get("nct_id") for e, r in pubs.items() if e.startswith("pubmed:none:")}
    for f in findings["findings"]:
        missing = [e for e in f["evidence_ids"] if e not in pubs]
        if missing:
            problems.append(f"cites ids no tool returned: {missing}")
        text = f"{f['claim']} {f.get('notes') or ''}"
        if PUBLISHED.search(f["claim"]) and not NEGATED.search(f["claim"]) and set(f["evidence_ids"]) & weak:
            problems.append(f"calls a mention or background article a results paper: {f['claim']!r}")
        if "no results publication" in text.lower() and not set(f["evidence_ids"]) & set(none_records):
            problems.append(f"says no results publication but cites the mentions, not the none record: {f['claim']!r}")
    for evidence_id, nct in none_records.items():
        said = any(evidence_id in f["evidence_ids"] and "no results publication" in f"{f['claim']} {f.get('notes') or ''}".lower()
                   for f in findings["findings"])
        if not said:
            problems.append(f"{nct}: no results candidate, but no finding says 'no results publication found' citing {evidence_id}")
    return problems


async def main() -> None:
    wanted = set(sys.argv[1:])
    for key, brief in BRIEFS.items():
        if wanted and not any(key.startswith(w) for w in wanted):
            continue
        state = RunState(brief)
        findings = (await run_researcher(state, Brief(lane="publications", brief=brief), f"researcher:publications#{key}")).model_dump()
        problems = check(state, findings)
        calls = [{"name": c["name"], "args": c["args"], "result": c["result"]} for c in state.tool_calls]
        out = {"brief": brief, "findings": findings, "problems": problems, "tool_calls": calls}
        (ROOT / "runs" / f"publications_{key}.json").write_text(json.dumps(out, indent=2, default=str))
        print(f"## {key}: {len(findings['findings'])} findings, {len(calls)} tool calls, problems {len(problems)}")
        for f in findings["findings"]:
            print(f"- {f['claim']} {f['evidence_ids']} ({f['confidence']})")
        for p in problems:
            print(f"  PROBLEM: {p}")
        print(f"  gaps: {findings['gaps']}\n", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
