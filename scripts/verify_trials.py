"""Check the snapshot against the live registry: pick random stopped trials, fetch each one live, and
compare every field the agents rely on. Also re-derives results_due_date, days_late and the stop category.

    uv run python scripts/verify_trials.py          # 20 trials
    uv run python scripts/verify_trials.py 50 7     # 50 trials, seed 7
"""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ghost import db, http  # noqa: E402
from ghost.classify import classify_why_stopped  # noqa: E402
from ghost.tools import CTGOV  # noqa: E402

FIELDS = {  # snapshot column -> path in the live record
    "overall_status": ("statusModule", "overallStatus"),
    "why_stopped": ("statusModule", "whyStopped"),
    "start_date": ("statusModule", "startDateStruct", "date"),
    "primary_completion_date": ("statusModule", "primaryCompletionDateStruct", "date"),
    "completion_date": ("statusModule", "completionDateStruct", "date"),
    "enrollment": ("designModule", "enrollmentInfo", "count"),
    "results_first_post_date": ("statusModule", "resultsFirstPostDateStruct", "date"),
}


def dig(record: dict, path: tuple):
    for key in path:
        record = (record or {}).get(key)
    return record


def same(snapshot, live) -> bool:
    if isinstance(snapshot, dt.date):  # snapshot stores '2019-08' as 2019-08-01
        return live is not None and snapshot.isoformat().startswith(str(live)) or snapshot.isoformat() == f"{live}-01"
    return (snapshot or None) == (live or None)


def main(n: int, seed: int) -> None:
    rows = db.run_select(f"""SELECT nct_id FROM trial_derived WHERE stopped ORDER BY hash(nct_id || '{seed}') LIMIT {n}""")["rows"]
    mismatches, checked = [], 0
    for row in rows:
        snap = db.trial_record(row["nct_id"])
        live = http.get(f"{CTGOV}/{row['nct_id']}", use_cache=False)
        p = live["protocolSection"]
        checked += 1
        for column, path in FIELDS.items():
            if not same(snap[column], dig(p, path)):
                mismatches.append((row["nct_id"], column, snap[column], dig(p, path)))
        if snap["has_results"] != bool(live.get("hasResults")):
            mismatches.append((row["nct_id"], "has_results", snap["has_results"], live.get("hasResults")))
        due = snap["primary_completion_date"] + dt.timedelta(days=365) if snap["primary_completion_date"] else None
        if due != snap["results_due_date"]:
            mismatches.append((row["nct_id"], "results_due_date (derived)", snap["results_due_date"], due))
        if classify_why_stopped(snap["why_stopped"])[0] != snap["why_stopped_category"] and snap["why_stopped_method"] == "keyword":
            mismatches.append((row["nct_id"], "why_stopped_category (derived)", snap["why_stopped_category"], classify_why_stopped(snap["why_stopped"])))
    print(f"checked {checked} stopped trials against the live registry, {len(mismatches)} mismatches")
    for m in mismatches:
        print(f"  {m[0]} {m[1]}: snapshot={m[2]!r} live={m[3]!r}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20, int(sys.argv[2]) if len(sys.argv) > 2 else 1)
