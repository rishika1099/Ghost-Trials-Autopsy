"""How the snapshot builder searches 8-Ks for a stopped trial and picks the passage it stores.
Cases come from the Phase 2 review of the first filings build."""

import datetime as dt
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build_snapshot_filings", ROOT / "scripts" / "build_snapshot.py")
build_snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_snapshot)


def test_drug_terms_split_combinations_and_drop_non_drugs():
    # NCT05065411 (Veru): the old search looked for the whole phrase and found nothing.
    assert build_snapshot.drug_terms(["Enobosarm & Abemaciclib Combo"]) == ["Enobosarm", "Abemaciclib"]
    assert build_snapshot.drug_terms(["Sasanlimab Prefilled syringe", "Encorafenib"]) == ["Sasanlimab", "Encorafenib"]
    assert build_snapshot.drug_terms(["VX-561 150 mg", "Placebo"]) == ["VX-561"]
    assert build_snapshot.drug_terms(["non-steroidal AI, or steroidal AI (exemestane with or without everolimus)"]) == [
        "exemestane", "everolimus"]


def test_filing_windows_surround_each_date_instead_of_spanning_them():
    # An Amgen trial was matched to an earnings release years after it stopped, because the window ran from
    # 120 days before the first date to 120 days after a registry update in 2024.
    trial = {"primary_completion_date": dt.date(2018, 1, 1), "completion_date": dt.date(2018, 3, 1),
             "last_update_date": dt.date(2023, 5, 1)}
    assert build_snapshot.filing_windows(trial) == [(dt.date(2017, 9, 3), dt.date(2018, 6, 29)),
                                                    (dt.date(2023, 1, 1), dt.date(2023, 8, 29))]


def test_plain_text_decodes_entities():
    assert build_snapshot.plain_text("<p>Repatha&#174; &#8226; sales&nbsp;up</p>") == "Repatha® • sales up"


def test_best_snippet_prefers_the_nct_id():
    doc = "<p>Sales of drugx rose.</p>" + "x " * 400 + "<p>The NCT01234567 study of drugx was terminated.</p>"
    snippet, relevance = build_snapshot.best_snippet(doc, "NCT01234567", ["drugx"], ["Asthma"])
    assert relevance == "nct_id" and "NCT01234567" in snippet


def test_best_snippet_prefers_stop_language_over_a_sales_table():
    doc = ("<p>Product sales: Drugx $40 million, Drugy $12 million.</p>" + "filler " * 200 +
           "<p>We discontinued the phase 2 trial of drugx after it did not meet its primary endpoint.</p>")
    snippet, relevance = build_snapshot.best_snippet(doc, "NCT01234567", ["drugx"], ["Asthma"])
    assert relevance == "drug_and_stop" and "did not meet its primary endpoint" in snippet


def test_best_snippet_labels_a_bare_mention_as_weakest():
    snippet, relevance = build_snapshot.best_snippet("<p>Pipeline: drugx, drugy, drugz.</p>", "NCT01234567", ["drugx"], ["Asthma"])
    assert relevance == "drug_only" and "drugx" in snippet


def test_best_snippet_with_no_mention():
    assert build_snapshot.best_snippet("<p>Nothing here.</p>", "NCT01234567", ["drugx"], []) == (None, None)
