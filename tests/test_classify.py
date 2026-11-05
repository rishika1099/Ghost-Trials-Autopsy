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
    # "safety" as data collected or a finding that was absent is not a safety reason
    ("Main Study was completed. LT-OLE was discontinued as sufficient safety data has been generated.", "unmatched"),
    ("This study served its purpose in providing considerable safety data.", "unmatched"),
    ("Study terminated by Sponsor due to absence of significant safety findings.", "unmatched"),
    ("Due to the lack of a clinical efficacy signal in the induction treatment phase, Seres closed the dosing phases of "
     "open label and maintenance portions of the study. Patients who had received prior doses were followed for safety data.", "efficacy"),
    ("An administrative decision was made to terminate the AT-1501-N205 study. This voluntary business-related decision "
     "was not related to the safety of tegoprubart (AT-1501). Available safety data demonstrated tegoprubart to be safe "
     "and well tolerated.", "business/strategic"),
    ("* slower than anticipated rate of enrollment * need to obtain safety and efficacy data in a timely manner * "
     "pending expiry of manufacturing materials/reagents", "enrollment"),
    ("Trial was terminated early to analyze the accumulated data and evaluate the efficacy, safety and future of "
     "palovarotene in MO.", "not safety"),
    ("Sponsor decision to analyze available safety and efficacy data", "business/strategic"),
    ("All primary efficacy data has been collected and analyzed. Based on the safety data gathered to date, it has been "
     "determined that continued participation by study subjects would not yield any additional beneficial safety "
     "information.", "not safety"),
    # still safety
    ("The study was terminated following review of safety data.", "safety"),
    ("Safety data review", "safety"),
    ("Due to implementation of an urgent safety measure, enrollment and dosing was stopped", "safety"),
    ("Study was stopped early due to lack of efficacy signal and safety concerns", "safety"),
]


@pytest.mark.parametrize("reason,category", CASES)
def test_keyword_rules(reason, category):
    got, method = classify_why_stopped(reason)
    if category == "unmatched":  # left for the LLM pass
        assert method == "unmatched", got
    elif category == "not safety":
        assert got != "safety"
    else:
        assert got == category


def test_blank_and_unmatched():
    assert classify_why_stopped(None) == ("blank", "blank")
    assert classify_why_stopped("  ") == ("blank", "blank")
    assert classify_why_stopped("As recommended by the Data and Safety Monitoring Board (DSMB)")[1] == "unmatched"
