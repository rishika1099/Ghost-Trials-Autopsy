"""Derived results columns: a trial that never enrolled anyone has no results to post, so no due date."""

import datetime as dt

from scripts.build_snapshot import derive

TODAY = dt.date(2026, 11, 5)


def trial(**kw):
    base = {"nct_id": "NCT00000001", "overall_status": "TERMINATED", "enrollment": 40, "why_stopped": "Lack of efficacy",
            "primary_completion_date": dt.date(2020, 1, 1), "has_results": False, "results_first_post_date": None}
    return {**base, **kw}


def test_unposted_trial_is_overdue():
    row = derive([trial()], TODAY, use_llm=False)[0]
    assert row["results_due_date"] == dt.date(2020, 12, 31)
    assert row["days_late"] == (TODAY - dt.date(2020, 12, 31)).days


def test_withdrawn_trial_has_no_due_date():
    row = derive([trial(overall_status="WITHDRAWN", enrollment=0, why_stopped="Business decision")], TODAY, use_llm=False)[0]
    assert row["results_due_date"] is None and row["days_late"] is None
    assert row["stopped"]


def test_zero_enrollment_has_no_due_date():
    row = derive([trial(enrollment=0)], TODAY, use_llm=False)[0]
    assert row["results_due_date"] is None and row["days_late"] is None
