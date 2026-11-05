"""Run only the disclosures researcher on the three sample queries, and check its quotes.

    uv run python scripts/run_disclosures.py          # s1, s2, s3
    uv run python scripts/run_disclosures.py s1       # one of them (s1 is vTv NCT03980730, per samples.json)

Each brief is what the Lead would send for that sample. For every finding, every "quoted phrase" must appear
word for word in a record the finding cites (a filing snippet or excerpt, or a registry field such as why_stopped),
normalized as ghost/citecheck.py does (case, spacing, curly quotes), and every cited evidence_id must exist. Outputs go to runs/disclosures_<id>.json.
"""

import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ghost.citecheck import _norm  # noqa: E402
from ghost.config import ROOT  # noqa: E402
from ghost.pipeline import Brief, run_researcher  # noqa: E402
from ghost.state import RunState  # noqa: E402

BRIEFS = {
    "s1_discrepancy": "Disclosures for vTv Therapeutics trial NCT03980730 (Elevage, azeliragon in mild Alzheimer's disease with "
                      "impaired glucose tolerance, phase 2, terminated; registry reason 'for business reasons'; primary completion "
                      "2020-12-01, completion 2021-01-29). Find what vTv told investors in 8-Ks about this trial near when it stopped. "
                      "Quote the 8-K language exactly and say whether it gives a reason.",
    "s2_never_posted": "Disclosures for Sorrento Therapeutics, Inc. trial NCT04903327 (COVI-MSC, phase 2, terminated; primary "
                       "completion 2022-08-29, completion 2022-11-23). Find what Sorrento told investors in 8-Ks about this trial "
                       "or COVI-MSC near when it stopped. Quote the 8-K language exactly and say whether it gives a reason.",
    "s3_sponsor": "Disclosures for Entero Therapeutics (formerly First Wave BioPharma and AzurRx BioPharma). Its stopped phase 2 "
                  "trials: NCT04858425 (terminated after topline data), NCT04839575 and NCT04243551 (terminated, enrollment), "
                  "NCT04542434 and NCT04436458 (withdrawn). For each, find what the company told investors in 8-Ks near the stop. "
                  "Quote the 8-K language exactly and say whether it gives a reason.",
}
QUOTE = re.compile(r"[\"“]([^\"”]{8,})[\"”]")


def strings(value) -> list[str]:
    """Every text value in a record: snippets, excerpts, and registry fields such as why_stopped."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in strings(v)]
    return []


def evidence_text(record) -> str:
    return _norm(" ".join([record.title, *strings(record.data)]))


def check_quotes(state: RunState, findings: dict) -> list[dict]:
    results = []
    for finding in findings["findings"]:
        cited = [state.store.get(e) for e in finding["evidence_ids"]]
        missing = [e for e, r in zip(finding["evidence_ids"], cited) if r is None]
        pool = " ".join(evidence_text(r) for r in cited if r)
        for text in (finding["claim"], finding.get("notes") or ""):
            for quote in QUOTE.findall(text):
                results.append({"quote": quote, "exact": _norm(quote) in pool, "cited": finding["evidence_ids"]})
        if missing:
            results.append({"quote": None, "exact": False, "cited": finding["evidence_ids"], "missing_ids": missing})
    return results


async def main() -> None:
    wanted = set(sys.argv[1:])
    for key, brief in BRIEFS.items():
        if wanted and not any(key.startswith(w) for w in wanted):
            continue
        state = RunState(brief)
        findings = (await run_researcher(state, Brief(lane="disclosures", brief=brief), f"researcher:disclosures#{key}")).model_dump()
        quotes = check_quotes(state, findings)
        calls = [{"name": c["name"], "args": c["args"], "result": c["result"]} for c in state.tool_calls]
        out = {"brief": brief, "findings": findings, "quote_check": quotes, "tool_calls": calls}
        (ROOT / "runs" / f"disclosures_{key}.json").write_text(json.dumps(out, indent=2, default=str))
        exact = sum(q["exact"] for q in quotes)
        print(f"## {key}: {len(findings['findings'])} findings, {len(calls)} tool calls, quotes exact {exact}/{len(quotes)}")
        for f in findings["findings"]:
            print(f"- {f['claim']} {f['evidence_ids']} ({f['confidence']})")
        for q in quotes:
            if not q["exact"]:
                print(f"  NOT EXACT: {q}")
        print(f"  gaps: {findings['gaps']}\n", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
