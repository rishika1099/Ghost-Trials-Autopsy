"""Each deterministic citation rule on its own: dates, quotes, overreach and table talk, with the edge cases
that matter (date formats, curly quotes, ellipses, negation)."""

import pytest

from ghost.citecheck import check_claim, dates_in, overreach_problems, plumbing_problems, quote_problems, record_text

RECORD = {"title": "A phase 2 trial of drug X", "data": {
    "nct_id": "NCT01234567", "start_date": "2017-03-05", "primary_completion_date": "2018-06-01",
    "why_stopped": "The sponsor’s decision to discontinue the program for business reasons."}}


@pytest.mark.parametrize("text, expected", [
    ("Started 2017-03-05.", {"2017-03-05"}),
    ("Started March 5, 2017.", {"2017-03-05"}),
    ("Started Mar. 5 2017.", {"2017-03-05"}),
    ("Started in March 2017.", {"2017-03"}),
    ("Started in mar 2017.", {"2017-03"}),
    ("No date here, only 2017 and 42 patients.", set()),
])
def test_dates_in_reads_the_usual_forms(text, expected):
    assert dates_in(text) == expected


def test_month_only_date_matches_a_full_date_in_the_record():
    assert check_claim("The trial started in March 2017.", [RECORD]) == []


def test_date_in_no_record_is_flagged():
    problems = check_claim("The trial started on 2017-03-06.", [RECORD])
    assert problems and "2017-03-06" in problems[0]


def test_wrong_month_is_flagged():
    assert check_claim("The trial started in April 2017.", [RECORD])


def test_a_date_with_no_records_is_flagged():
    assert check_claim("It stopped on 2018-06-01.", [])


def test_quote_with_curly_marks_and_apostrophe_matches():
    claim = "The registry says “the sponsor's decision to discontinue the program”."
    assert check_claim(claim, [RECORD]) == []


def test_quote_with_an_ellipsis_matches_each_piece():
    claim = '"The sponsor’s decision ... for business reasons."'
    assert quote_problems(claim, record_text([RECORD])) == []


def test_altered_quote_is_flagged():
    claim = 'The registry says "the sponsor decided to end the program early".'
    assert check_claim(claim, [RECORD])


def test_short_quoted_terms_are_left_to_the_model():
    assert quote_problems('It was a "business decision".', record_text([RECORD])) == []


@pytest.mark.parametrize("claim", [
    "The company hid the results.",
    "Sponsor concealed the safety signal.",
    "This shows they broke the law.",
    "The 8-K was misleading.",
    "Results were withheld.",
    "They deliberately buried the data.",
])
def test_overreach_is_flagged(claim):
    assert overreach_problems(claim)


@pytest.mark.parametrize("claim", [
    "A mismatch is not proof that the company hid anything.",
    "The records cannot show whether anyone broke the law.",
    "This is never evidence of being misled.",
    "The trial was terminated for business reasons.",
])
def test_negated_or_neutral_wording_passes(claim):
    assert overreach_problems(claim) == []


@pytest.mark.parametrize("claim", [
    "The filings table contains zero rows for this sponsor.",
    "The snapshot is empty for this drug.",
    "Our query returned 0 rows.",
    "The database has no matching records.",
])
def test_table_talk_is_flagged(claim):
    assert plumbing_problems(claim)


def test_plain_not_found_wording_passes():
    assert plumbing_problems("No 8-K was found from 2018-01-01 to 2018-12-31 for CIK 0000000001.") == []


def test_empty_claim_has_no_problems():
    assert check_claim("", [RECORD]) == []
