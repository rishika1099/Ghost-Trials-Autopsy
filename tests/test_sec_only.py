"""--sec-only rebuilds sponsor_cik and filings and leaves every other table exactly as it was.

Offline: http.get is replaced by recorded SEC responses and fails on any other host, and the LLM classifier
fails if called, so the test also proves --sec-only makes no ClinicalTrials.gov, PubMed or Gemini calls."""

import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlparse

import duckdb
import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build_snapshot", ROOT / "scripts" / "build_snapshot.py")
build_snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_snapshot)

UNTOUCHED = ("trials", "trial_derived", "publications")

# Response shapes as SEC returns them (company_tickers.json, EDGAR full-text search, one archive document).
# The CIK, accession and text are made up for the test; they are not real filings.
TICKERS = {"0": {"cik_str": 1863990, "ticker": "VERU", "title": "Veru Inc."},
           "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
SUBMISSIONS = {"sic": "2834", "filings": {"recent": {"form": ["8-K", "10-Q"], "filingDate": ["2022-11-10", "2022-08-01"]}}}
NO_ENTITIES = {"hits": {"hits": []}}
EFTS_HIT = {"hits": {"hits": [{"_id": "0001863990-22-000099:ex99.htm",
                               "_source": {"form": "8-K", "file_date": "2022-11-10"}}]}}
DOCUMENT = "<html><body><p>Veru announced that the Phase 3 trial of enobosarm (NCT05065411) will stop.</p></body></html>"


def fake_get(url, params=None, *, as_json=True, use_cache=True):
    host = urlparse(url).netloc
    if url == build_snapshot.TICKERS:
        return TICKERS
    if url == build_snapshot.EFTS:
        return NO_ENTITIES if "keysTyped" in (params or {}) else EFTS_HIT
    if host == "data.sec.gov" and "/submissions/" in url:
        return SUBMISSIONS
    if host == "www.sec.gov" and "/Archives/" in url:
        return DOCUMENT
    raise AssertionError(f"--sec-only must not call {host}")


def no_llm(*args, **kwargs):
    raise AssertionError("--sec-only must not call the LLM classifier")


def make_snapshot(path: Path) -> None:
    db = duckdb.connect(str(path))
    db.execute("""CREATE TABLE trials (nct_id VARCHAR PRIMARY KEY, title VARCHAR, sponsor VARCHAR, sponsor_class VARCHAR,
        phase VARCHAR, conditions VARCHAR[], interventions VARCHAR[], drug_names VARCHAR[], overall_status VARCHAR,
        why_stopped VARCHAR, start_date DATE, primary_completion_date DATE, completion_date DATE, enrollment INTEGER,
        has_results BOOLEAN, results_first_post_date DATE, last_update_date DATE)""")
    db.executemany("INSERT INTO trials VALUES (" + ",".join("?" * 17) + ")", [
        ["NCT05065411", "Enobosarm and abemaciclib in breast cancer", "Veru Inc.", "INDUSTRY", "PHASE3", ["Breast Cancer"],
         ["Enobosarm & Abemaciclib Combo"], ["Enobosarm & Abemaciclib Combo"], "TERMINATED", "Business decision", dt.date(2021, 5, 1), dt.date(2022, 6, 1), dt.date(2022, 9, 1),
         204, False, None, dt.date(2022, 12, 1)],
        ["NCT00000002", "A completed trial", "Private Pharma GmbH", "INDUSTRY", "PHASE2", ["Asthma"], ["drugx"], ["drugx"],
         "COMPLETED", None, dt.date(2016, 1, 1), dt.date(2017, 1, 1), dt.date(2017, 3, 1), 50, True, dt.date(2018, 1, 1),
         dt.date(2018, 2, 1)],
    ])
    db.execute("""CREATE TABLE trial_derived (nct_id VARCHAR PRIMARY KEY, results_due_date DATE, results_posted BOOLEAN,
        days_late INTEGER, stopped BOOLEAN, why_stopped_category VARCHAR, why_stopped_method VARCHAR)""")
    db.executemany("INSERT INTO trial_derived VALUES (?,?,?,?,?,?,?)", [
        ["NCT05065411", dt.date(2023, 6, 1), False, 1200, True, "business/strategic", "llm"],
        ["NCT00000002", dt.date(2018, 1, 1), True, 0, False, "blank", "blank"],
    ])
    db.execute("""CREATE TABLE publications (nct_id VARCHAR, pmid VARCHAR, link_type VARCHAR, title VARCHAR,
        journal VARCHAR, pub_date DATE, url VARCHAR)""")
    db.execute("INSERT INTO publications VALUES ('NCT00000002', '12345678', 'pubmed_si', 'A paper', 'A journal', "
               "DATE '2019-01-01', 'https://pubmed.ncbi.nlm.nih.gov/12345678/')")
    build_snapshot.write_sec_tables(db, [], [])
    build_snapshot.write_snapshot_meta(db, {t: dt.date(2026, 11, 1) for t in build_snapshot.SNAPSHOT_TABLES})
    db.close()


def fingerprint(path: Path) -> dict[str, tuple[int, str]]:
    db = duckdb.connect(str(path), read_only=True)
    out = {}
    for table in UNTOUCHED:
        rows = db.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall()
        out[table] = (len(rows), hashlib.sha256(repr(rows).encode()).hexdigest())
    db.close()
    return out


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    db_path, mappings_path = tmp_path / "autopsy.duckdb", tmp_path / "mappings.json"
    make_snapshot(db_path)
    monkeypatch.setattr(build_snapshot, "DB_PATH", db_path)
    monkeypatch.setattr(build_snapshot, "MAPPINGS_PATH", mappings_path)
    monkeypatch.setattr(build_snapshot, "SEC_USER_AGENT", "test contact")
    monkeypatch.setattr(build_snapshot.http, "get", fake_get)
    monkeypatch.setattr(build_snapshot, "llm_classify", no_llm)
    return db_path, mappings_path


def test_sec_only_leaves_other_tables_unchanged(snapshot):
    db_path, _ = snapshot
    before = fingerprint(db_path)
    build_snapshot.main(["--sec-only"])
    assert fingerprint(db_path) == before


def test_sec_only_builds_sec_tables_and_meta(snapshot):
    db_path, mappings_path = snapshot
    build_snapshot.main(["--sec-only"])
    db = duckdb.connect(str(db_path), read_only=True)
    assert db.execute("SELECT sponsor, cik, ticker, match_method, sic, files_8k FROM sponsor_cik").fetchall() == [
        ("Veru Inc.", "0001863990", "VERU", "exact_core", "2834", True)]
    filings = db.execute("SELECT nct_id, accession, form, filed_date, snippet, relevance, matched_terms FROM filings").fetchall()
    assert len(filings) == 1
    nct, accession, form, filed, snippet, relevance, terms = filings[0]
    assert (nct, accession, form, filed, relevance) == ("NCT05065411", "0001863990-22-000099", "8-K", dt.date(2022, 11, 10), "nct_id")
    assert terms == ["NCT05065411", "Enobosarm", "Abemaciclib"]
    assert "NCT05065411" in snippet and "<" not in snippet
    meta = dict(db.execute("SELECT table_name, row_count FROM snapshot_meta").fetchall())
    assert meta == {"trials": 2, "trial_derived": 2, "sponsor_cik": 1, "filings": 1, "publications": 1}
    built = dict(db.execute("SELECT table_name, built_at FROM snapshot_meta").fetchall())
    assert built["trials"] == dt.date(2026, 11, 1)  # untouched tables keep their build date
    db.close()
    tables = {t["table"] for t in json.loads(mappings_path.read_text())["tables"]}
    assert {"sponsor_cik", "filings"} <= tables


def test_sec_only_refuses_without_user_agent(snapshot, monkeypatch):
    db_path, _ = snapshot
    before = fingerprint(db_path)
    monkeypatch.setattr(build_snapshot, "SEC_USER_AGENT", "")
    with pytest.raises(SystemExit):
        build_snapshot.main(["--sec-only"])
    assert fingerprint(db_path) == before
