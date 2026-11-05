"""The why_stopped keyword rules, on reasons that tripped earlier versions."""

import pytest

from ghost.classify import classify_why_stopped

CASES = [
    ("Lack of efficacy", "efficacy"),
    ("Primary endpoint was not met", "efficacy"),
    ("Adverse event", "safety"),
    ("Slow enrollment", "enrollment"),
    ("Corporate business decision. Not due to safety or efficacy concerns.", "business/strategic"),
    ("Sponsor decision; Not a safety decision", "business/strategic"),
    ("This study was canceled before enrollment due to a decision by the Sponsor", "business/strategic"),
    ("Enrollment into this study was terminated by the Sponsor prior to completion for strategic reasons.", "business/strategic"),
    ("Administrative reasons.", "business/strategic"),
    ("Did not meet enrollment target", "enrollment"),
]


@pytest.mark.parametrize("reason,category", CASES)
def test_keyword_rules(reason, category):
    assert classify_why_stopped(reason)[0] == category


def test_blank_and_unmatched():
    assert classify_why_stopped(None) == ("blank", "blank")
    assert classify_why_stopped("  ") == ("blank", "blank")
    assert classify_why_stopped("As recommended by the Data and Safety Monitoring Board (DSMB)")[1] == "unmatched"
