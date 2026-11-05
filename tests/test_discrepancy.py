"""Registry reason vs. 8-K language rules (ghost/discrepancy.py), on real 8-K sentences from the Phase 4 review."""

import re

from ghost import discrepancy as d


def test_efficacy_means_a_failure_not_a_mention():
    assert d.categories("On December 15, 2020, vTv announced that the phase 2 Elevage Study of azeliragon did not meet its primary objective.") == ["efficacy"]
    assert "efficacy" in d.categories("ATA188 Primary Endpoint of Confirmed Disability Improvement at 12 Months Not Achieved")
    assert d.categories("The trial met its primary endpoint of overall survival.") == ["positive"]


def test_enrollment_expectations_are_not_efficacy():
    # Sage: "did not meet enrollment expectations" was read as an efficacy failure by the first rules.
    cats = d.categories("The trial did not meet enrollment expectations and was closed to enrollment this quarter.")
    assert cats == ["enrollment"]


def test_safety_means_a_concern_not_a_profile():
    assert d.categories("Pamrevlumab was generally safe and well tolerated with a favorable safety profile.") == []
    assert d.categories("The clinical hold was prompted by deaths at the highest dose of an ongoing toxicology study.") == ["safety"]
    assert d.categories("The decision was not based on any safety concerns.") == []


def test_bare_strategic_is_not_a_business_reason():
    assert d.categories("Excludes one-time costs related to strategic actions.") == []
    assert d.categories("The study was stopped as part of a strategic reprioritization of the pipeline.") == ["business/strategic"]


def test_scope_this_other_or_program():
    assert d.scope("The NCT01234567 study did not meet its primary endpoint.", "NCT01234567", "") == "this_trial"
    assert d.scope("The Phase 3 RELEASE MSS1 trial (NCT04657666) did not meet the primary endpoint.", "NCT01234567", "") == "other_trial"
    assert d.scope("Topline results from LELANTOS-2, a Phase 3 Clinical Study of Pamrevlumab", "NCT01234567", "") == "other_trial"
    assert d.scope("The ENABLAR-2 trial of enobosarm will proceed.", "NCT05065411", "ENABLAR-2: enobosarm and abemaciclib") == "this_trial"
    assert d.scope("Pamrevlumab did not meet the primary endpoint.", "NCT01234567", "") == "drug_program"


def test_biomarkers_are_not_trial_acronyms():
    # Veru: HER2 in both the title and the sentence made a sentence about another trial look like this one.
    assert d.acronyms("Enobosarm With Abemaciclib in ER+HER2- Metastatic Breast Cancer, CD20, TP53") == set()
    assert d.acronyms("the ENABLAR-2 study, EMBOLD and PIVOT IO-001") == {"ENABLAR-2", "EMBOLD", "PIVOT IO-001"}


def test_labels():
    assert d.label("business/strategic", {"efficacy"})[0] == "discrepancy"
    assert d.label("enrollment", {"safety"})[0] == "discrepancy"
    assert d.label("efficacy", {"positive"})[0] == "discrepancy"
    assert d.label("efficacy", {"efficacy"})[0] == "consistent"
    assert d.label("blank", {"efficacy"})[0] == "registry_blank_8k_reason"
    assert d.label("business/strategic", {"enrollment"})[0] == "different_reason"
    assert d.label("safety", set())[0] == "no_reason_in_8k"


def test_strength_ranks_the_headline_case_first():
    named = d.strength("discrepancy", "registry business/strategic; 8-K efficacy", "this_trial", "nct_id",
                       "Strategic decision, not due to efficacy", 30)
    program = d.strength("discrepancy", "registry business/strategic; 8-K efficacy", "drug_program", "drug_and_stop", "Sponsor decision", 200)
    reverse = d.strength("discrepancy", "registry efficacy; 8-K business/strategic", "this_trial", "drug_and_stop", "Futility", 30)
    other = d.strength("discrepancy", "registry business/strategic; 8-K efficacy", "other_trial", "drug_and_stop", "x", 30)
    assert named > program > reverse > other == 0
    assert named == 10


def test_long_quotes_stay_exact_substrings():
    sentence = "x " * 300 + "the study did not meet its primary endpoint " + "y " * 300
    quote = d.quote_of(sentence, "efficacy")
    assert quote in sentence and "did not meet its primary endpoint" in quote and len(quote) <= d.MAX_QUOTE


def test_hand_checked_rows_are_complete_and_neutral():
    banned = re.compile(r"\b(hid|hidden|conceal\w*|mislead\w*|misled|lied|lie|deceiv\w*|illegal|broke the law)\b", re.I)
    for row in d.HAND_CHECKED:
        assert re.fullmatch(r"NCT\d{8}", row["nct_id"]) and re.fullmatch(r"\d{10}-\d{2}-\d{6}", row["accession"])
        assert row["filing_url"].startswith("https://www.sec.gov/Archives/") and row["label"] in ("discrepancy", "consistent")
        assert not banned.search(row["rule"]) and "—" not in row["sec_quote"] + row["rule"]
