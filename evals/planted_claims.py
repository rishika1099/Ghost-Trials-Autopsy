"""How many planted errors does the Citation Checker catch? 10 claims with one planted error each (wrong date,
misquote, overreaching word, wrong status) and 10 correct controls, all citing real records.

    uv run python evals/planted_claims.py --build   # freeze the records into evals/planted_claims.json (snapshot + SEC)
    uv run python evals/planted_claims.py           # score the deterministic rules (offline)
    uv run python evals/planted_claims.py --model   # score the full Checker: rules + Gemini (needs Vertex credentials)

A planted claim is caught when the Checker removes it or fixes it into text that no longer has the error. A control
is a false positive when the Checker removes or changes it.
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURE = ROOT / "evals" / "planted_claims.json"

VERU, VTV, SORRENTO = "ctgov:NCT05065411", "ctgov:NCT03980730", "ctgov:NCT04903327"
VTV_8K, ALLAKOS_8K, VERU_8K = "sec:0001564590-21-008154", "sec:0000950170-24-004686", "sec:0001193125-24-133757"

PLANTED = [
    {"error": "wrong date", "text": "Veru's NCT05065411 reached primary completion on 2023-11-19.", "cites": [VERU], "wrong": "2023-11-19"},
    {"error": "wrong date", "text": "vTv filed the 8-K about Elevage on 2021-02-14.", "cites": [VTV_8K], "wrong": "2021-02-14"},
    {"error": "wrong date", "text": "Sorrento's NCT04903327 was completed on 2022-12-23.", "cites": [SORRENTO], "wrong": "2022-12-23"},
    {"error": "misquote", "text": "vTv's 8-K says the phase 2 Elevage Study of azeliragon \"failed to meet its primary objective\".",
     "cites": [VTV_8K], "wrong": "failed to meet"},
    {"error": "misquote", "text": "Allakos announced that its \"Phase 2 Lirentelimab Trials in Atopic Dermatitis and Chronic Spontaneous Urticaria Missed Their Primary Endpoints\".",
     "cites": [ALLAKOS_8K], "wrong": "Missed"},
    {"error": "misquote", "text": "The registry gives \"Strategic business decision\" as the reason NCT05065411 stopped.", "cites": [VERU],
     "wrong": "Strategic business decision"},
    {"error": "overreach", "text": "Veru hid the outcome of ENABLAR-2 by calling its termination a business decision.", "cites": [VERU, VERU_8K], "wrong": "hid"},
    {"error": "overreach", "text": "vTv misled the registry by giving business reasons while its 8-K reported that Elevage did not meet its primary objective.",
     "cites": [VTV, VTV_8K], "wrong": "misled"},
    {"error": "overreach", "text": "Sorrento withheld the results of NCT04903327 from ClinicalTrials.gov.", "cites": [SORRENTO], "wrong": "withheld"},
    {"error": "wrong status and reason", "text": "The registry lists NCT04903327 as withdrawn because of safety concerns.", "cites": [SORRENTO],
     "wrong": "safety"},
]
CONTROLS = [
    {"text": "NCT05065411 was terminated, and its registry reason is \"Business decision\".", "cites": [VERU]},
    {"text": "Primary completion of NCT05065411 was on 2023-10-19.", "cites": [VERU]},
    {"text": "vTv's 8-K filed on 2021-02-24 says \"the phase 2 Elevage Study of azeliragon did not meet its primary objective\".", "cites": [VTV_8K]},
    {"text": "On December 15, 2020, vTv announced that the Elevage study did not meet its primary objective.", "cites": [VTV_8K]},
    {"text": "The registry gives \"for business reasons\" as the reason NCT03980730 stopped.", "cites": [VTV]},
    {"text": "Allakos announced that its Phase 2 lirentelimab trials in chronic spontaneous urticaria did not meet their primary endpoints.",
     "cites": [ALLAKOS_8K]},
    {"text": "NCT04903327 was terminated \"Due to considerably slow enrollment, unable to reach enrollment targets\".", "cites": [SORRENTO]},
    {"text": "NCT04903327 reached primary completion in August 2022.", "cites": [SORRENTO]},
    {"text": "The registry reason for NCT03980730 differs from the 8-K language; that is a discrepancy, not evidence that vTv hid anything.",
     "cites": [VTV, VTV_8K]},
    {"text": "Veru's 8-K filed on 2024-05-08 describes ENABLAR-2 as \"subject to the availability of sufficient funding\".", "cites": [VERU_8K]},
]


def build() -> None:
    """Freeze the cited records: registry records from the snapshot, 8-K excerpts from SEC's archive."""
    from ghost import db, http, sec
    from ghost.tools import _paragraphs

    records = {}
    for evidence_id in (VERU, VTV, SORRENTO):
        nct = evidence_id.split(":")[1]
        records[evidence_id] = {"evidence_id": evidence_id, "title": db.trial_record(nct)["title"],
                                "source_url": f"https://clinicaltrials.gov/study/{nct}",
                                "data": json.loads(json.dumps(db.trial_record(nct), default=str))}
    filings = {
        VTV_8K: ("https://www.sec.gov/Archives/edgar/data/1641489/000156459021008154/vtvt-ex991_6.htm", "2021-02-24", ["Elevage"]),
        ALLAKOS_8K: ("https://www.sec.gov/Archives/edgar/data/1564824/000095017024004686/allk-ex99_2.htm", "2024-01-16", ["Primary Endpoints", "MAVERICK"]),
        VERU_8K: ("https://www.sec.gov/Archives/edgar/data/863894/000119312524133757/d820381dex991.htm", "2024-05-08", ["ENABLAR-2"]),
    }
    for evidence_id, (url, filed, keywords) in filings.items():
        excerpts = [p[:900] for p in _paragraphs(http.get(url, as_json=False)) if any(k.lower() in p.lower() for k in keywords)][:4]
        records[evidence_id] = {"evidence_id": evidence_id, "title": f"8-K filed {filed}", "source_url": url,
                                "data": {"accession": evidence_id.split(":")[1], "form": "8-K", "filed_date": filed, "url": url, "excerpts": excerpts}}
    assert sec  # the same plain-text conversion the tools use
    FIXTURE.write_text(json.dumps({"records": records, "planted": PLANTED, "controls": CONTROLS}, indent=2, ensure_ascii=False))
    print(f"wrote {FIXTURE.relative_to(ROOT)}")


def load() -> dict:
    return json.loads(FIXTURE.read_text())


def caught(original: dict, after: str | None) -> bool:
    """Removed, or fixed into text that no longer contains the planted error."""
    return after is None or original["wrong"].lower() not in after.lower()


async def score(use_model: bool) -> dict:
    from ghost import pipeline
    from ghost.pipeline import Claim, WriterReport
    from ghost.state import RunState

    data = load()
    state = RunState("planted claims")
    for record in data["records"].values():
        state.store.add(record["evidence_id"], record["title"], record["source_url"], record["data"])
    items = [dict(c, kind="planted") for c in data["planted"]] + [dict(c, kind="control") for c in data["controls"]]
    report = WriterReport(answer=[], evidence=[Claim(text=c["text"], citations=c["cites"]) for c in items], differences=[],
                          cant_tell=["x"], timeline_text="")
    if not use_model:
        async def no_model(state, claims, **kwargs):
            raise RuntimeError("rules-only scoring: the model pass is off")
        pipeline.run_checker = no_model
    checked, stats = await pipeline.check_citations(state, report)
    by_text = {d["claim"]: d for d in stats["decisions"]}
    rows = []
    for item in items:
        decision = by_text[item["text"]]
        after = None if decision["action"] == "removed" else decision.get("fixed_text", item["text"])
        if item["kind"] == "planted":
            rows.append({**item, "action": decision["action"], "by": decision["by"], "caught": caught(item, after), "reason": decision.get("reason", "")})
        else:
            rows.append({**item, "action": decision["action"], "by": decision["by"], "false_positive": decision["action"] != "kept",
                         "reason": decision.get("reason", "")})
    planted = [r for r in rows if r["kind"] == "planted"]
    controls = [r for r in rows if r["kind"] == "control"]
    return {"mode": "rules+model" if use_model else "rules only", "caught": sum(r["caught"] for r in planted), "planted": len(planted),
            "false_positives": sum(r["false_positive"] for r in controls), "controls": len(controls), "model_pass": stats["model_pass"],
            "rows": rows}


def main() -> None:
    if "--build" in sys.argv:
        build()
        return
    result = asyncio.run(score("--model" in sys.argv))
    print(f"{result['mode']}: caught {result['caught']}/{result['planted']} planted errors, "
          f"{result['false_positives']}/{result['controls']} controls wrongly changed (model pass ran: {result['model_pass']})")
    for r in result["rows"]:
        flag = ("CAUGHT" if r["caught"] else "MISSED") if r["kind"] == "planted" else ("FALSE POSITIVE" if r["false_positive"] else "ok")
        print(f"- [{flag}] {r.get('error', 'control')}: {r['action']} by {r['by']}. {r['text']}" + (f"  ({r['reason']})" if r["reason"] else ""))


if __name__ == "__main__":
    main()
