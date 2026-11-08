"""Turn the checked WriterReport into markdown, a numbered source list, and timeline JSON.

Numbering is done here, not by the model: sources are numbered in order of first citation, so every
[n] maps to exactly one evidence record, and every source's title, type and URL come from the store.
"""

import datetime as dt
import re

from ghost import db
from ghost.state import RunState

TRIAL_EVENTS = [
    ("start_date", "Start", "start"),
    ("primary_completion_date", "Primary completion", "stop"),
    ("completion_date", "Completion", "stop"),
    ("results_due_date", "Results due (approx.)", "due"),
    ("results_first_post_date", "Results posted", "posted"),
]


def clarification_markdown(plan) -> str:
    lines = [plan.message.strip()]
    if plan.options:
        lines += ["", "Try one of these:"] + [f"- {o}" for o in plan.options]
    return "\n".join(lines)


def _number_sources(sections: dict) -> tuple[list[str], dict[str, int]]:
    order: list[str] = []
    for claims in sections.values():
        for claim in claims:
            for evidence_id in claim.citations:
                if evidence_id not in order:
                    order.append(evidence_id)
    return order, {e: n for n, e in enumerate(order, 1)}


def _cite(claim, numbers: dict[str, int]) -> str:
    marks = "".join(f"[{numbers[e]}]" for e in claim.citations if e in numbers)
    return f"{claim.text.rstrip()} {marks}".strip()


def _date(value) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()[:10]
    return str(value)[:10]


RUN_LIMITS_RE = re.compile(r"\b(time|round|research|turn)\s+(budget|cap|limit)s?\b|\bturn caps?\b|\bstopped early because\b", re.I)


def _mentions_run_limits(sentence: str) -> bool:
    """True for a cant_tell sentence about our own run limits (time budget, round or turn caps)."""
    return bool(RUN_LIMITS_RE.search(sentence))


def build_timeline(state: RunState, cited: list[str]) -> list[dict]:
    """One timeline per trial cited in the report (or found, if the report cites none): registry dates,
    results due and posted (or a never-posted marker), 8-K dates and publication dates."""
    trial_ids = [e for e in cited if e.startswith("ctgov:")] or [e for e in state.store.records if e.startswith("ctgov:")][:3]
    timelines = []
    for evidence_id in trial_ids[:6]:
        record = state.store.get(evidence_id)
        data = dict(record.data)
        nct = data.get("nct_id") or evidence_id.split(":", 1)[1]
        if "results_due_date" not in data and db.DB_PATH.exists():
            data = {**(db.trial_record(nct) or {}), **data}
        events = []
        for key, label, kind in TRIAL_EVENTS:
            date = _date(data.get(key))
            if date:
                events.append({"date": date, "label": label, "kind": kind, "evidence_id": evidence_id})
        posted = data.get("has_results") or data.get("results_posted")
        if not posted and data.get("results_due_date"):
            events.append({"date": None, "label": "Results never posted", "kind": "never", "evidence_id": evidence_id})
        if data.get("overall_status") in ("TERMINATED", "WITHDRAWN", "SUSPENDED") and data.get("last_update_date"):
            events.append({"date": _date(data["last_update_date"]), "label": "Last registry update", "kind": "update", "evidence_id": evidence_id})
        single = len(trial_ids) == 1
        for other in state.store.records.values():
            if other.evidence_id.startswith("sec:") and (other.data.get("nct_id") == nct or (single and other.evidence_id in cited)):
                if other.data.get("filed_date"):
                    events.append({"date": _date(other.data["filed_date"]), "label": f"SEC {other.data.get('form') or 'filing'}",
                                   "kind": "filing", "evidence_id": other.evidence_id})
            if other.evidence_id.startswith("pubmed:") and (other.data.get("nct_id") == nct or nct in (other.data.get("nct_ids") or [])):
                # A review that only names the trial, or a paper from before it started, is not its publication.
                if other.data.get("pub_date") and other.data.get("link_strength", "results_candidate") == "results_candidate":
                    events.append({"date": _date(other.data["pub_date"]), "label": "Publication", "kind": "publication",
                                   "evidence_id": other.evidence_id})
        events.sort(key=lambda e: e["date"] or "9999")
        timelines.append({"nct_id": nct, "title": data.get("title"), "sponsor": data.get("sponsor"),
                          "status": data.get("overall_status"), "why_stopped": data.get("why_stopped"), "events": events})
    return timelines


def timeline_from_events(timeline: list[dict]) -> str:
    """A plain text timeline built from the records, used when the Writer's text is missing or failed the check."""
    lines = []
    for t in timeline:
        events = "; ".join(f"{e['label']} {e['date']}" if e["date"] else e["label"] for e in t["events"])
        if events:
            lines.append(f"{t['nct_id']}: {events}.")
    return "\n".join(lines)


def default_cant_tell(state: RunState) -> list[str]:
    """Used only when no limitation survived filtering, so the section is never empty. Picked by what was found."""
    ids = list(state.store.records)
    lines = ["The registry reason is what the sponsor reported; the records can't show the full reason a trial stopped."]
    if not any(i.startswith("sec:") for i in ids):
        lines.append("No SEC filing was found for this question, so there is no investor story to compare; "
                     "private sponsors file nothing with the SEC.")
    else:
        lines.append("A registry reason that differs from a filing is a discrepancy between sources, not proof of intent.")
    if not any(i.startswith("pubmed:") for i in ids):
        lines.append("No linked paper was found in PubMed or Europe PMC; results in conference abstracts or on company "
                     "websites would be missed.")
    lines.append("The results due date is an approximation, so a late or missing posting is not evidence that anyone broke the law.")
    return lines


def render(state: RunState, report, checker: dict) -> dict:
    sections = {"answer": report.answer, "evidence": report.evidence, "differences": report.differences}
    order, numbers = _number_sources(sections)
    sources = []
    for evidence_id in order:
        record = state.store.get(evidence_id)
        sources.append({"n": numbers[evidence_id], "evidence_id": evidence_id, "title": record.title,
                        "source_type": record.source_type, "url": record.source_url})
    timeline = build_timeline(state, order)

    lines = ["## Answer", " ".join(_cite(c, numbers) for c in report.answer) or "The evidence gathered does not support a direct answer.", ""]
    timeline_text = report.timeline_text.strip() or timeline_from_events(timeline)
    lines += ["## Timeline", timeline_text or "No dated events were found.", ""]
    lines += ["## Evidence"] + ([f"- {_cite(c, numbers)}" for c in report.evidence] or ["- No claim survived the citation check."]) + [""]
    if report.differences:
        lines += ["## Where the stories differ"] + [f"- {_cite(c, numbers)}" for c in report.differences] + [""]
    # Only the time budget limits the answer in a way the reader needs to know; other notes are for the trace.
    # The model sometimes adds its own budget sentence even when research finished; only the code's note is true.
    cant = [c for c in report.cant_tell if not _mentions_run_limits(c)] + [n for n in state.notes if "budget" in n]
    cant = cant or default_cant_tell(state)
    lines += ["## What the data can't tell us"] + [f"- {c}" for c in cant] + [""]
    lines += ["## Sources"] + [f"{s['n']}. {s['title']}. {s['source_type']}. {s['url']}" for s in sources]
    lines += ["", f"_Snapshot date: {db.snapshot_date() or 'unknown'}. Research rounds: {state.rounds}. "
              f"citations_checked: {checker['citations_checked']}, removed: {checker['removed']}._"]
    return {
        "markdown": "\n".join(lines),
        "report": {"answer": [_cite(c, numbers) for c in report.answer], "evidence": [_cite(c, numbers) for c in report.evidence],
                   "differences": [_cite(c, numbers) for c in report.differences], "cant_tell": cant,
                   "timeline_text": timeline_text},
        "sources": sources,
        "timeline": timeline,
    }
