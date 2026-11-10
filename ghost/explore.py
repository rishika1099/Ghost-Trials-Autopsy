"""Instant views of the snapshot for the Explore section of the page: no model calls, only SQL.

- ledger(): headline numbers and two breakdowns for the whole snapshot.
- sponsor_search(q) and sponsor_card(name): a report card for one sponsor, ranked against its peers.
- differ_wall(): stopped trials whose registry reason and 8-K language disagree.

Definitions match get_snapshot_stats, so the page and the agents never disagree:
- "enrolled" means the trial has a results due date (a withdrawn trial never enrolled anyone).
- "silent" means stopped, enrolled, no results on ClinicalTrials.gov and no linked article
  (ctgov_result, pubmed_si or ctgov_derived) published after the trial started.
"""

import datetime as dt

from ghost import db

REPO_DATA_URL = "https://github.com/rishika1099/Ghost-Trials-Autopsy/tree/main/data"
PEER_MIN_ENROLLED_STOPPED = 5  # sponsors with fewer stopped-and-enrolled trials are not ranked

LINKED_PUB = """EXISTS (SELECT 1 FROM publications p WHERE p.nct_id = t.nct_id
    AND p.link_type IN ('ctgov_result', 'pubmed_si', 'ctgov_derived')
    AND (p.pub_date IS NULL OR t.start_date IS NULL OR p.pub_date >= t.start_date))"""

# One row per trial with the flags every view needs.
FLAGS = f"""
SELECT t.nct_id, t.title, t.sponsor, t.phase, t.overall_status, t.why_stopped, t.enrollment,
       t.start_date, t.primary_completion_date, t.conditions,
       d.stopped, d.results_posted, d.days_late, d.why_stopped_category,
       d.results_due_date IS NOT NULL AS enrolled,
       {LINKED_PUB} AS linked_pub,
       d.stopped AND d.results_due_date IS NOT NULL AND NOT d.results_posted AND NOT {LINKED_PUB} AS silent
FROM trials t JOIN trial_derived d USING (nct_id)
"""


def _rows(sql: str, params: list | None = None) -> list[dict]:
    with db.connection().cursor() as cursor:
        cursor.execute(sql, params or [])
        columns = [c[0] for c in cursor.description or []]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _plain(value):
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 1)
    return value


def _clean(rows: list[dict]) -> list[dict]:
    return [{k: _plain(v) for k, v in row.items()} for row in rows]


def _pct(part, whole) -> float | None:
    return round(100.0 * part / whole, 1) if whole else None


def ledger() -> dict:
    """Headline numbers plus breakdowns by stated reason and by completion year."""
    head = _rows(f"""
        WITH f AS ({FLAGS})
        SELECT count(*) AS trials,
               count(*) FILTER (WHERE stopped) AS stopped,
               count(*) FILTER (WHERE stopped AND enrolled) AS stopped_enrolled,
               count(*) FILTER (WHERE stopped AND enrolled AND NOT results_posted) AS stopped_no_results,
               count(*) FILTER (WHERE silent) AS silent,
               coalesce(sum(enrollment) FILTER (WHERE silent), 0) AS silent_participants,
               count(*) FILTER (WHERE NOT stopped) AS completed,
               count(*) FILTER (WHERE NOT stopped AND results_posted) AS completed_posted,
               count(*) FILTER (WHERE stopped AND enrolled AND results_posted) AS stopped_posted,
               count(*) FILTER (WHERE stopped AND why_stopped_category = 'blank') AS stopped_blank_reason
        FROM f""")[0]
    head["pct_stopped_posted"] = _pct(head["stopped_posted"], head["stopped_enrolled"])
    head["pct_completed_posted"] = _pct(head["completed_posted"], head["completed"])
    head["pct_silent"] = _pct(head["silent"], head["stopped_enrolled"])
    by_reason = _rows(f"""
        WITH f AS ({FLAGS})
        SELECT why_stopped_category AS reason, count(*) AS stopped_enrolled,
               count(*) FILTER (WHERE results_posted) AS posted, count(*) FILTER (WHERE silent) AS silent
        FROM f WHERE stopped AND enrolled GROUP BY 1 ORDER BY stopped_enrolled DESC""")
    by_year = _rows(f"""
        WITH f AS ({FLAGS})
        SELECT year(primary_completion_date) AS year,
               count(*) FILTER (WHERE stopped AND enrolled) AS stopped_enrolled,
               count(*) FILTER (WHERE stopped AND enrolled AND results_posted) AS stopped_posted,
               count(*) FILTER (WHERE NOT stopped) AS completed,
               count(*) FILTER (WHERE NOT stopped AND results_posted) AS completed_posted
        FROM f WHERE primary_completion_date IS NOT NULL GROUP BY 1 ORDER BY 1""")
    for row in by_reason:
        row["pct_posted"] = _pct(row["posted"], row["stopped_enrolled"])
        row["pct_silent"] = _pct(row["silent"], row["stopped_enrolled"])
    for row in by_year:
        row["pct_stopped_posted"] = _pct(row["stopped_posted"], row["stopped_enrolled"])
        row["pct_completed_posted"] = _pct(row["completed_posted"], row["completed"])
    return {"headline": head, "by_reason": by_reason, "by_year": by_year, "snapshot_date": db.snapshot_date(),
            "source_url": REPO_DATA_URL, "definitions": DEFINITIONS}


DEFINITIONS = {
    "stopped": "Registry status TERMINATED, WITHDRAWN or SUSPENDED.",
    "enrolled": "The trial has a results due date (primary completion plus one year). Withdrawn trials never enrolled anyone.",
    "silent": ("Stopped after enrolling people, with no results on ClinicalTrials.gov and no article linked to the trial "
               "(by the registry or by PubMed) published after it started."),
    "participants": "Enrollment as the sponsor registered it. For a stopped trial this is usually the actual number enrolled.",
}


def sponsor_search(q: str, limit: int = 8) -> list[dict]:
    q = (q or "").strip()
    if len(q) < 2:
        return []
    return _rows("""SELECT sponsor, count(*) AS trials FROM trials WHERE sponsor ILIKE ? GROUP BY 1
                    ORDER BY (sponsor ILIKE ?) DESC, trials DESC, sponsor LIMIT ?""", [f"%{q}%", f"{q}%", limit])


def _peer_table() -> list[dict]:
    return _rows(f"""
        WITH f AS ({FLAGS})
        SELECT sponsor, count(*) FILTER (WHERE stopped AND enrolled) AS stopped_enrolled,
               count(*) FILTER (WHERE silent) AS silent
        FROM f GROUP BY 1 HAVING count(*) FILTER (WHERE stopped AND enrolled) >= ?""", [PEER_MIN_ENROLLED_STOPPED])


def sponsor_card(name: str) -> dict | None:
    """Report card for one sponsor (exact name from sponsor_search, or the best partial match)."""
    match = _rows("SELECT sponsor FROM trials WHERE sponsor = ? LIMIT 1", [name]) or sponsor_search(name, 1)
    if not match:
        return None
    sponsor = match[0]["sponsor"]
    head = _rows(f"""
        WITH f AS ({FLAGS})
        SELECT count(*) AS trials, count(*) FILTER (WHERE stopped) AS stopped,
               count(*) FILTER (WHERE stopped AND enrolled) AS stopped_enrolled,
               count(*) FILTER (WHERE stopped AND enrolled AND results_posted) AS stopped_posted,
               count(*) FILTER (WHERE silent) AS silent,
               coalesce(sum(enrollment) FILTER (WHERE silent), 0) AS silent_participants,
               count(*) FILTER (WHERE stopped AND why_stopped_category = 'blank') AS blank_reason,
               median(days_late) FILTER (WHERE results_posted) AS median_days_late
        FROM f WHERE sponsor = ?""", [sponsor])[0]
    head["pct_silent"] = _pct(head["silent"], head["stopped_enrolled"])
    head["pct_stopped_posted"] = _pct(head["stopped_posted"], head["stopped_enrolled"])
    reasons = _rows("""SELECT d.why_stopped_category AS reason, count(*) AS n FROM trials t JOIN trial_derived d USING (nct_id)
                       WHERE t.sponsor = ? AND d.stopped GROUP BY 1 ORDER BY n DESC""", [sponsor])
    sec = _rows("SELECT cik, ticker, company, match_score FROM sponsor_cik WHERE sponsor = ? ORDER BY match_score DESC LIMIT 1", [sponsor])
    differ = _rows("""SELECT count(DISTINCT nct_id) AS trials,
                             count(DISTINCT nct_id) FILTER (WHERE decided_by = 'hand_checked' OR scope = 'this_trial') AS named
                      FROM discrepancies WHERE sponsor = ? AND label = 'discrepancy'""", [sponsor])[0]
    trials = _rows(f"""
        WITH f AS ({FLAGS})
        SELECT f.nct_id, f.title, f.phase, f.overall_status, f.why_stopped, f.why_stopped_category, f.enrollment,
               f.primary_completion_date, f.results_posted, f.linked_pub, f.silent,
               EXISTS (SELECT 1 FROM discrepancies x WHERE x.nct_id = f.nct_id AND x.label = 'discrepancy') AS differs
        FROM f WHERE sponsor = ? AND stopped
        ORDER BY silent DESC, primary_completion_date DESC NULLS LAST LIMIT 40""", [sponsor])
    peers = _peer_table()
    rank = None
    if head["stopped_enrolled"] >= PEER_MIN_ENROLLED_STOPPED:
        mine = head["pct_silent"] or 0
        rates = [_pct(p["silent"], p["stopped_enrolled"]) or 0 for p in peers]
        rank = {"peers": len(rates), "share_more_silent": _pct(sum(r > mine for r in rates), len(rates)),
                "share_less_silent": _pct(sum(r < mine for r in rates), len(rates)), "min_stopped": PEER_MIN_ENROLLED_STOPPED}
    base = ledger()["headline"]
    return {"sponsor": sponsor, "headline": _clean([head])[0], "reasons": reasons, "sec": _clean(sec)[0] if sec else None,
            "differ": differ, "trials": _clean(trials), "rank": rank,
            "baseline": {"pct_silent": base["pct_silent"], "pct_stopped_posted": base["pct_stopped_posted"]},
            "source_url": REPO_DATA_URL, "definitions": DEFINITIONS}


def leaderboard(limit: int = 8) -> dict:
    """Sponsors with at least PEER_MIN_ENROLLED_STOPPED stopped-and-enrolled trials, by silent share, both ends."""
    peers = _peer_table()
    for p in peers:
        p["pct_silent"] = _pct(p["silent"], p["stopped_enrolled"])
    most = sorted(peers, key=lambda p: (-p["pct_silent"], -p["stopped_enrolled"], p["sponsor"]))[:limit]
    least = sorted(peers, key=lambda p: (p["pct_silent"], -p["stopped_enrolled"], p["sponsor"]))[:limit]
    return {"min_stopped": PEER_MIN_ENROLLED_STOPPED, "peers": len(peers), "most_silent": most, "least_silent": least}


def differ_wall(limit: int = 80) -> dict:
    """Best 8-K row per trial labelled 'discrepancy': hand-checked first, then rows whose 8-K names the trial, then leads."""
    rows = _rows("""
        SELECT d.nct_id, d.sponsor, t.title, t.overall_status, d.registry_reason, d.registry_category, d.sec_categories,
               d.sec_quote, d.filed_date, d.filing_url, d.accession, d.scope, d.decided_by, d.strength
        FROM discrepancies d JOIN trials t USING (nct_id)
        WHERE d.label = 'discrepancy'
        QUALIFY row_number() OVER (PARTITION BY d.nct_id ORDER BY d.decided_by = 'hand_checked' DESC,
                                   d.scope = 'this_trial' DESC, d.strength DESC, d.filed_date) = 1
        ORDER BY d.decided_by = 'hand_checked' DESC, d.scope = 'this_trial' DESC, d.strength DESC, d.nct_id
        LIMIT ?""", [limit])
    for row in rows:
        row["kind"] = ("hand_checked" if row["decided_by"] == "hand_checked"
                       else "names_trial" if row["scope"] == "this_trial" else "drug_lead")
    return {"trials": _clean(rows), "source_url": REPO_DATA_URL,
            "note": ("Keyword rules compare the registry's stated reason with 8-K sentences. 'Names this trial' means the 8-K "
                     "sentence names the trial; a 'drug lead' names only the drug, so it may be about another trial. "
                     "A difference is a discrepancy between two public statements, not evidence of intent.")}
