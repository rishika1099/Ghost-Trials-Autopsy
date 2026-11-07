"""Check find_publications' live fallback on stopped trials that have nothing in the snapshot's publications table.
Calls PubMed and Europe PMC for real (no model calls), prints what each trial gets and saves it.

    uv run python scripts/check_publications_live.py            # 5 trials picked from the snapshot
    uv run python scripts/check_publications_live.py NCT01234567 NCT07654321

For each trial it shows which sources were searched, how many articles came back per link_strength, and the
"No results publication found" record when there is no results_candidate. Output: runs/publications_live_check.json
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ghost import db, tools  # noqa: E402
from ghost.config import ROOT  # noqa: E402
from ghost.state import RunState  # noqa: E402

PICK = """SELECT t.nct_id, t.sponsor, t.drug_names[1] AS drug FROM trials t JOIN trial_derived d USING (nct_id)
WHERE d.stopped AND d.results_due_date IS NOT NULL AND t.nct_id NOT IN (SELECT nct_id FROM publications)
ORDER BY hash(t.nct_id) LIMIT 5"""


def main(nct_ids: list[str]) -> None:
    if nct_ids:
        trials = [{"nct_id": n, **(db.trial_record(n) or {})} for n in nct_ids]
        trials = [{"nct_id": t["nct_id"], "sponsor": t.get("sponsor"), "drug": (t.get("drug_names") or [None])[0]} for t in trials]
    else:
        trials = db.run_select(PICK)["rows"]
    out = []
    for trial in trials:
        state = RunState("live publications check")
        result = tools.trial_publications(state, trial["nct_id"], trial.get("drug"))
        strengths = Counter(p["link_strength"] for p in result.get("publications", []))
        print(f"{trial['nct_id']} ({trial.get('sponsor')}, {trial.get('drug')}): searched {', '.join(result.get('searched', []))}; "
              f"{dict(strengths) or 'no articles'}")
        for pub in result.get("publications", [])[:5]:
            print(f"   {pub['link_strength']:<17} PMID {pub['pmid']} {pub.get('pub_date') or '?'}: {(pub.get('title') or '')[:90]}")
        if result.get("evidence_id"):
            print(f"   cite {result['evidence_id']}: {state.store.get(result['evidence_id']).title}")
        out.append({"trial": trial, "result": result})
    path = ROOT / "runs" / "publications_live_check.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nSaved {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main(sys.argv[1:])
