"""Sponsor to SEC company matching, on real cases from the first sponsor_cik build (Phase 2 review)."""

from ghost.names import compatible, core_key, core_name, match_sponsors, normalize

# Shaped like SEC's company_tickers.json: {title: (cik, ticker)}. Titles are real SEC titles; CIKs and SIC
# codes are only there to tell companies apart and are not all SEC's real values.
COMPANIES = {
    "Atea Pharmaceuticals, Inc.": ("0001593899", "AVIR"),
    "Spero Therapeutics, Inc.": ("0001701108", "SPRO"),
    "Keros Therapeutics, Inc.": ("0001664710", "KROS"),
    "Athene Holding Ltd.": ("0001527469", "ATH-PA"),
    "HERON THERAPEUTICS, INC. /DE/": ("0000818033", "HRTX"),
    "VERTEX PHARMACEUTICALS INC / MA": ("0000875320", "VRTX"),
    "DR REDDYS LABORATORIES LTD": ("0001135951", "RDY"),
    "Dare Bioscience, Inc.": ("0001401914", "DARE"),
    "Rocket Lab Corp": ("0001819994", "RKLB"),
    "ROCKET PHARMACEUTICALS, INC.": ("0001281895", "RCKT"),
    "EDISON INTERNATIONAL": ("0000827052", "EIX"),
    "CONSOLIDATED EDISON INC": ("0001047862", "ED"),
    "UNITED THERAPEUTICS Corp": ("0001082554", "UTHR"),
    "UNITED PARCEL SERVICE INC": ("0001090727", "UPS"),
    "NOVARTIS AG": ("0001114448", "NVS"),
    "Biohaven Ltd.": ("0001935979", "BHVN"),
    "Meridian Corp": ("0001750735", "MRBK"),
    "Merck & Co., Inc.": ("0000310158", "MRK"),
}
SIC = {"0001593899": "2834", "0001701108": "2834", "0001664710": "2834", "0001527469": "6311", "0000818033": "2834",
       "0000875320": "2834", "0001135951": "2834", "0001401914": "2834", "0001819994": "3760", "0001281895": "2836",
       "0000827052": "4911", "0001047862": "4931", "0001082554": "2834", "0001090727": "4513", "0001114448": "2834",
       "0001935979": "2834", "0001750735": "6022", "0000310158": "2834"}


def match(sponsor: str, sic: bool = True) -> str | None:
    rows = match_sponsors({sponsor}, COMPANIES, SIC.get if sic else None)
    return rows[0]["company"] if rows else None


def test_normalize_strips_state_tags_accents_and_apostrophes():
    assert normalize("HERON THERAPEUTICS, INC. /DE/") == "heron therapeutics"
    assert normalize("VERTEX PHARMACEUTICALS INC / MA") == "vertex pharmaceuticals"
    assert core_key("Dr. Reddy's Laboratories Limited") == core_key("DR REDDYS LABORATORIES LTD") == "drreddys"
    assert core_name("Daré Bioscience, Inc.") == "dare"


def test_shared_generic_word_is_not_a_match():
    # Each of these scored 92.3 or more under the old whole-name fuzzy match.
    assert match("AFT Pharmaceuticals, Ltd.") is None
    assert match("Esperion Therapeutics, Inc.") is None
    assert match("Akero Therapeutics, Inc") is None
    assert match("Athenex, Inc.") is None


def test_same_company_with_different_suffixes_matches():
    assert match("Heron Therapeutics") == "HERON THERAPEUTICS, INC. /DE/"
    assert match("Vertex Pharmaceuticals Incorporated") == "VERTEX PHARMACEUTICALS INC / MA"
    assert match("Dr. Reddy's Laboratories Limited") == "DR REDDYS LABORATORIES LTD"
    assert match("Daré Bioscience, Inc.") == "Dare Bioscience, Inc."
    assert match("Novartis Pharmaceuticals") == "NOVARTIS AG"
    assert match("Biohaven Pharmaceuticals, Inc.") == "Biohaven Ltd."


def test_shared_core_picks_the_drug_company():
    assert match("Rocket Pharmaceuticals Inc.") == "ROCKET PHARMACEUTICALS, INC."


def test_ambiguous_core_needs_the_full_name():
    assert match("Edison Pharmaceuticals Inc") is None
    assert match("United BioPharma") is None


def test_sic_check_rejects_non_health_companies():
    assert match("Meridian Bioscience, Inc.") is None
    assert match("Meridian Bioscience, Inc.", sic=False) == "Meridian Corp"  # what the names alone would do


def test_override_maps_subsidiary_to_parent():
    rows = match_sponsors({"Merck Sharp & Dohme LLC", "Janssen Research & Development, LLC"}, COMPANIES, SIC.get)
    by_sponsor = {r["sponsor"]: (r["cik"], r["match_method"]) for r in rows}
    assert by_sponsor["Merck Sharp & Dohme LLC"] == ("0000310158", "override")
    assert by_sponsor["Janssen Research & Development, LLC"] == ("0000200406", "override")


def test_industries_must_agree():
    assert not compatible("Arena Pharmaceuticals", "Arena Group Holdings")
    assert not compatible("Cogna Technology Solutions LLC", "Cogna Therapeutics")
    assert compatible("Pacira Pharmaceuticals, Inc", "Pacira BioSciences, Inc.")


def test_override_follows_a_renamed_filer():
    # The s3 sample sponsor: CIK 1604191 has been AzurRx, First Wave BioPharma, Entero Therapeutics and now
    # GridAI Technologies (an electric-services SIC), so neither the ticker list nor EDGAR's name search finds it.
    rows = match_sponsors({"Entero Therapeutics", "AzurRx SAS", "First Wave Bio, Inc."}, COMPANIES, SIC.get)
    assert {r["sponsor"]: r["cik"] for r in rows} == {
        "Entero Therapeutics": "0001604191", "AzurRx SAS": "0001604191", "First Wave Bio, Inc.": "0001604191"}
