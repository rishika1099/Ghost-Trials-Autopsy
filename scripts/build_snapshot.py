"""Build the offline snapshot: data/autopsy.duckdb plus data/mappings.json.

    uv run python scripts/build_snapshot.py            # everything
    uv run python scripts/build_snapshot.py --skip-sec # no SEC_USER_AGENT yet
    uv run python scripts/build_snapshot.py --skip-llm # keyword rules only for why_stopped

Steps (each one is cached on disk under .cache/http, so a re-run is fast):
 1. trials          ClinicalTrials.gov API v2: industry, interventional, phase 2/3, primary completion 2015 to 2023
 2. trial_derived   results due date, posted or not, days late, stopped, why_stopped category
 3. sponsor_cik     sponsor name -> SEC CIK, fuzzy matched against company_tickers.json
 4. filings         8-Ks from matched sponsors near each stopped trial's dates that mention the drug or NCT ID
 5. publications    PMIDs from the registry's own references, PubMed [si] links, Europe PMC fallback
 6. snapshot_meta   build date and row counts
 7. mappings.json   every column's type, description and valid values (the Text2SQL context layer)
"""

import argparse
import datetime as dt
import json
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ghost import http  # noqa: E402
from ghost.config import DATA_DIR, DB_PATH, MAPPINGS_PATH, SEC_USER_AGENT  # noqa: E402
from ghost.classify import classify_why_stopped, llm_classify  # noqa: E402
from ghost.names import match_sponsors  # noqa: E402

CTGOV = "https://clinicaltrials.gov/api/v2/studies"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EFTS = "https://efts.sec.gov/LATEST/search-index"
TICKERS = "https://www.sec.gov/files/company_tickers.json"

FILTER = (
    "AREA[StudyType]INTERVENTIONAL AND AREA[LeadSponsorClass]INDUSTRY AND "
    "(AREA[Phase]PHASE2 OR AREA[Phase]PHASE3) AND AREA[PrimaryCompletionDate]RANGE[2015-01-01,2023-12-31]"
)
STATUSES = "TERMINATED|WITHDRAWN|SUSPENDED|COMPLETED"
FIELDS = ",".join([
    "NCTId", "BriefTitle", "LeadSponsorName", "LeadSponsorClass", "Phase", "Condition",
    "InterventionName", "InterventionType", "OverallStatus", "WhyStopped", "StartDate",
    "PrimaryCompletionDate", "CompletionDate", "EnrollmentCount", "HasResults",
    "ResultsFirstPostDate", "LastUpdatePostDate", "ReferencePMID", "ReferenceType",
])
FILING_WINDOW_DAYS = 120
MAX_FILINGS_PER_TRIAL = 3
STOPPED = ("TERMINATED", "WITHDRAWN", "SUSPENDED")


def log(message: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {message}", flush=True)


def to_date(value: str | None) -> dt.date | None:
    """'2019-08' -> 2019-08-01, '2019-08-14' -> itself, None -> None."""
    if not value:
        return None
    parts = value.split("-")
    try:
        return dt.date(int(parts[0]), int(parts[1]) if len(parts) > 1 else 1, int(parts[2]) if len(parts) > 2 else 1)
    except ValueError:
        return None


# --- 1. Trials ---


def fetch_trials() -> tuple[list[dict], list[dict]]:
    trials, references = [], []
    token = None
    while True:
        params = {"filter.advanced": FILTER, "filter.overallStatus": STATUSES, "fields": FIELDS, "pageSize": 1000}
        if token:
            params["pageToken"] = token
        page = http.get(CTGOV, params)
        for study in page.get("studies", []):
            p = study.get("protocolSection", {})
            ident, status = p.get("identificationModule", {}), p.get("statusModule", {})
            sponsor = p.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})
            design = p.get("designModule", {})
            interventions = p.get("armsInterventionsModule", {}).get("interventions", [])
            nct = ident.get("nctId")
            trials.append({
                "nct_id": nct,
                "title": ident.get("briefTitle"),
                "sponsor": sponsor.get("name"),
                "sponsor_class": sponsor.get("class"),
                "phase": "/".join(design.get("phases", [])),
                "conditions": p.get("conditionsModule", {}).get("conditions", []),
                "interventions": [i.get("name") for i in interventions if i.get("name")],
                "drug_names": [
                    i.get("name") for i in interventions
                    if i.get("type") in ("DRUG", "BIOLOGICAL") and i.get("name") and "placebo" not in i["name"].lower()
                ],
                "overall_status": status.get("overallStatus"),
                "why_stopped": status.get("whyStopped"),
                "start_date": to_date(status.get("startDateStruct", {}).get("date")),
                "primary_completion_date": to_date(status.get("primaryCompletionDateStruct", {}).get("date")),
                "completion_date": to_date(status.get("completionDateStruct", {}).get("date")),
                "enrollment": design.get("enrollmentInfo", {}).get("count"),
                "has_results": bool(study.get("hasResults")),
                "results_first_post_date": to_date(status.get("resultsFirstPostDateStruct", {}).get("date")),
                "last_update_date": to_date(status.get("lastUpdatePostDateStruct", {}).get("date")),
            })
            for ref in p.get("referencesModule", {}).get("references", []):
                if ref.get("pmid") and ref.get("type") in ("RESULT", "DERIVED"):
                    references.append({"nct_id": nct, "pmid": ref["pmid"], "link_type": f"ctgov_{ref['type'].lower()}"})
        log(f"trials: {len(trials)} of {page.get('totalCount', '?')}" if not token else f"trials: {len(trials)}")
        token = page.get("nextPageToken")
        if not token:
            return trials, references


# --- 2. Derived columns ---


def derive(trials: list[dict], today: dt.date, use_llm: bool) -> list[dict]:
    rows = []
    for t in trials:
        due = t["primary_completion_date"] + dt.timedelta(days=365) if t["primary_completion_date"] else None
        posted = t["has_results"]
        if due is None:
            days_late = None
        elif posted and t["results_first_post_date"]:
            days_late = max(0, (t["results_first_post_date"] - due).days)
        elif not posted and today > due:
            days_late = (today - due).days  # still not posted: days overdue as of the snapshot date
        else:
            days_late = None
        category, method = classify_why_stopped(t["why_stopped"])
        rows.append({
            "nct_id": t["nct_id"],
            "results_due_date": due,
            "results_posted": posted,
            "days_late": days_late,
            "stopped": t["overall_status"] in STOPPED,
            "why_stopped_category": category,
            "why_stopped_method": method,
        })
    if use_llm:
        pending = {r["nct_id"]: t["why_stopped"] for r, t in zip(rows, trials) if r["why_stopped_method"] == "unmatched"}
        log(f"why_stopped: {len(pending)} reasons left for the LLM pass")
        labels = llm_classify(pending)
        for r in rows:
            if r["nct_id"] in labels:
                r["why_stopped_category"], r["why_stopped_method"] = labels[r["nct_id"]], "llm"
    for r in rows:
        if r["why_stopped_method"] == "unmatched":
            r["why_stopped_category"], r["why_stopped_method"] = "other", "default"
    return rows


# --- 3. Sponsor to CIK ---


def sponsor_ciks(sponsors: set[str]) -> list[dict]:
    tickers = http.get(TICKERS)
    companies = {}
    for row in tickers.values():
        companies.setdefault(row["title"], (str(row["cik_str"]).zfill(10), row["ticker"]))
    return match_sponsors(sponsors, companies)


# --- 4. Filings ---


def _paragraph(text: str, keywords: list[str], width: int = 600) -> str | None:
    """The first stretch of text around any keyword, tags stripped."""
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = re.sub(r"&nbsp;|&#160;", " ", plain)
    plain = re.sub(r"\s+", " ", plain)
    for keyword in keywords:
        at = plain.lower().find(keyword.lower())
        if at >= 0:
            start = max(0, at - width // 3)
            return plain[start : start + width].strip()
    return None


def fetch_filings(trials: list[dict], cik_by_sponsor: dict[str, str]) -> list[dict]:
    rows, seen = [], set()
    stopped = [t for t in trials if t["overall_status"] in STOPPED and t["sponsor"] in cik_by_sponsor]
    log(f"filings: searching EDGAR for {len(stopped)} stopped trials with a public sponsor")
    for n, t in enumerate(stopped, 1):
        anchors = [d for d in (t["completion_date"], t["primary_completion_date"], t["last_update_date"]) if d]
        if not anchors:
            continue
        start = min(anchors) - dt.timedelta(days=FILING_WINDOW_DAYS)
        end = max(anchors) + dt.timedelta(days=FILING_WINDOW_DAYS)
        terms = [t["nct_id"]] + [d for d in t["drug_names"][:2] if len(d) >= 4]
        query = " OR ".join(f'"{term}"' for term in terms)
        cik = cik_by_sponsor[t["sponsor"]]
        try:
            result = http.get(EFTS, {"q": query, "forms": "8-K", "ciks": cik, "dateRange": "custom",
                                     "startdt": start.isoformat(), "enddt": end.isoformat()})
        except http.SourceError as e:
            log(f"filings: {t['nct_id']} search failed: {e}")
            continue
        hits = (result or {}).get("hits", {}).get("hits", [])[:MAX_FILINGS_PER_TRIAL]
        for hit in hits:
            source = hit.get("_source", {})
            accession, _, filename = hit.get("_id", "").partition(":")
            if not accession or (t["nct_id"], accession) in seen:
                continue
            seen.add((t["nct_id"], accession))
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{filename}"
            try:
                snippet = _paragraph(http.get(url, as_json=False), terms)
            except http.SourceError:
                snippet = None
            rows.append({
                "nct_id": t["nct_id"], "cik": cik, "accession": accession, "form": source.get("form") or source.get("root_form"),
                "filed_date": to_date(source.get("file_date")), "url": url, "matched_terms": terms, "snippet": snippet,
            })
        if n % 100 == 0:
            log(f"filings: {n}/{len(stopped)} trials searched, {len(rows)} filings")
    return rows


# --- 5. Publications ---


def pubmed_si_links(nct_ids: list[str]) -> list[dict]:
    """PubMed articles whose secondary-source ID field lists the NCT ID. Batched: 40 NCT IDs per search."""
    links = []
    for i in range(0, len(nct_ids), 40):
        batch = nct_ids[i : i + 40]
        term = " OR ".join(f"{n}[si]" for n in batch)
        found = http.get(f"{EUTILS}/esearch.fcgi", {"db": "pubmed", "term": term, "retmode": "json", "retmax": 500})
        pmids = found.get("esearchresult", {}).get("idlist", [])
        if not pmids:
            continue
        xml = http.get(f"{EUTILS}/efetch.fcgi", {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}, as_json=False)
        wanted = set(batch)
        for article in ET.fromstring(xml).iter("PubmedArticle"):
            pmid = article.findtext(".//PMID")
            for accession in article.iter("AccessionNumber"):
                if (accession.text or "").strip().upper() in wanted:
                    links.append({"nct_id": accession.text.strip().upper(), "pmid": pmid, "link_type": "pubmed_si"})
        if (i // 40) % 25 == 0:
            log(f"publications: PubMed [si] {i + len(batch)}/{len(nct_ids)} trials, {len(links)} links")
    return links


def europepmc_links(nct_ids: list[str]) -> list[dict]:
    """Europe PMC is slow per request, so run a few at once. ghost.http still spaces them under the rate limit."""

    def one(nct: str) -> list[dict]:
        try:
            found = http.get(EUROPEPMC, {"query": f'"{nct}" AND SRC:MED', "format": "json", "pageSize": 5, "resultType": "lite"})
        except http.SourceError:
            return []
        return [{"nct_id": nct, "pmid": hit["pmid"], "link_type": "europepmc_mention"}
                for hit in (found or {}).get("resultList", {}).get("result", []) if hit.get("pmid")]

    links = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for n, found in enumerate(pool.map(one, nct_ids), 1):
            links.extend(found)
            if n % 250 == 0:
                log(f"publications: Europe PMC {n}/{len(nct_ids)}, {len(links)} links")
    return links


def pubmed_details(pmids: list[str]) -> dict[str, dict]:
    details = {}
    for i in range(0, len(pmids), 200):
        batch = pmids[i : i + 200]
        summary = http.get(f"{EUTILS}/esummary.fcgi", {"db": "pubmed", "id": ",".join(batch), "retmode": "json"})
        result = summary.get("result", {})
        for pmid in result.get("uids", []):
            doc = result[pmid]
            sort = (doc.get("sortpubdate") or "")[:10].replace("/", "-")
            details[pmid] = {"title": doc.get("title"), "journal": doc.get("fulljournalname") or doc.get("source"),
                             "pub_date": to_date(sort) if sort else None}
        if (i // 200) % 10 == 0:
            log(f"publications: details {i + len(batch)}/{len(pmids)}")
    return details


# --- 7. Mappings (the Text2SQL context layer) ---

DESCRIPTIONS = {
    "trials": {
        "_table": "One row per trial from ClinicalTrials.gov: industry-sponsored, interventional, phase 2 or 3, primary completion 2015 to 2023.",
        "nct_id": "ClinicalTrials.gov ID, e.g. NCT01234567. Primary key; joins every other table.",
        "title": "Brief title of the trial.",
        "sponsor": "Lead sponsor name exactly as registered. Use ILIKE '%name%' to match: spelling varies.",
        "sponsor_class": "Lead sponsor class. Always INDUSTRY in this snapshot.",
        "phase": "Phase, e.g. PHASE2, PHASE3, or PHASE2/PHASE3 for combined trials.",
        "conditions": "List of conditions studied (VARCHAR[]). Search with list_contains or array_to_string(conditions, ' ') ILIKE.",
        "interventions": "List of intervention names (VARCHAR[]), including placebo and devices.",
        "drug_names": "Drug and biologic intervention names without placebo (VARCHAR[]). Use these to search filings.",
        "overall_status": "Registry status: TERMINATED, WITHDRAWN, SUSPENDED or COMPLETED.",
        "why_stopped": "The sponsor's free-text reason for stopping, as registered. NULL when completed or left blank.",
        "start_date": "Trial start date (month-only dates become the 1st).",
        "primary_completion_date": "Date the last participant was examined for the primary outcome.",
        "completion_date": "Date the whole trial ended.",
        "enrollment": "Number of participants enrolled (actual for stopped trials).",
        "has_results": "TRUE if summary results are posted on ClinicalTrials.gov.",
        "results_first_post_date": "Date results were first posted. NULL if never posted.",
        "last_update_date": "Date the registry record was last updated.",
    },
    "trial_derived": {
        "_table": "Derived columns per trial, built by scripts/build_snapshot.py. Join on nct_id.",
        "nct_id": "Trial ID; joins trials.nct_id.",
        "results_due_date": "Approximate results deadline: primary completion + 365 days. An approximation, not a legal deadline.",
        "results_posted": "TRUE if results are posted on ClinicalTrials.gov.",
        "days_late": "If posted: days after results_due_date it was posted (0 = on time). If not posted and past due: days overdue as of the snapshot date. NULL otherwise.",
        "stopped": "TRUE if status is TERMINATED, WITHDRAWN or SUSPENDED.",
        "why_stopped_category": "Category of the stated reason: safety, efficacy, business/strategic, enrollment, other, or blank.",
        "why_stopped_method": "How the category was assigned: keyword, llm, blank, or default.",
    },
    "sponsor_cik": {
        "_table": "Sponsor name to SEC CIK for publicly listed sponsors. Private sponsors have no row.",
        "sponsor": "Sponsor name as in trials.sponsor.",
        "cik": "SEC Central Index Key, 10 digits zero-padded.",
        "ticker": "Stock ticker.",
        "company": "Company name in SEC's list.",
        "match_score": "Fuzzy match score 0 to 100 between the normalized names. Only rows >= the threshold are kept.",
    },
    "filings": {
        "_table": "SEC 8-K filings from a matched sponsor within 120 days of a stopped trial's dates that mention its NCT ID or drug name.",
        "nct_id": "Trial the filing was matched to.",
        "cik": "Filer's CIK.",
        "accession": "SEC accession number, e.g. 0001193125-21-123456.",
        "form": "Form type, e.g. 8-K.",
        "filed_date": "Date filed with the SEC.",
        "url": "URL of the matching document in the EDGAR archive.",
        "matched_terms": "Search terms used (NCT ID and drug names).",
        "snippet": "About 600 characters of the filing around the first matching term. NULL if the document could not be read.",
    },
    "publications": {
        "_table": "PubMed articles linked to a trial.",
        "nct_id": "Trial ID.",
        "pmid": "PubMed ID.",
        "link_type": "How it was linked: ctgov_result (sponsor listed it as a results paper), ctgov_derived or pubmed_si (the article lists the NCT ID), europepmc_mention (text mentions the NCT ID).",
        "title": "Article title.",
        "journal": "Journal name.",
        "pub_date": "Publication date.",
        "url": "PubMed URL.",
    },
    "snapshot_meta": {
        "_table": "One row per table: when the snapshot was built and how many rows each table has.",
        "table_name": "Table name.", "row_count": "Rows in that table.", "built_at": "Snapshot build date (UTC).",
        "scope": "What the snapshot covers.",
    },
}
MAX_ENUM_VALUES = 12


def write_mappings(db: duckdb.DuckDBPyConnection) -> None:
    tables = []
    for table, notes in DESCRIPTIONS.items():
        columns = []
        for name, dtype, *_ in db.execute(f"DESCRIBE {table}").fetchall():
            column = {"name": name, "type": dtype, "description": notes.get(name, "")}
            if dtype in ("VARCHAR", "BOOLEAN") and name not in ("nct_id", "url", "snippet", "title", "why_stopped"):
                values = db.execute(f"SELECT DISTINCT {name} FROM {table} WHERE {name} IS NOT NULL LIMIT {MAX_ENUM_VALUES + 1}").fetchall()
                if len(values) <= MAX_ENUM_VALUES:
                    column["enum_values"] = sorted(str(v[0]) for v in values)
            columns.append(column)
        tables.append({"table": table, "description": notes["_table"], "columns": columns})
    MAPPINGS_PATH.write_text(json.dumps({"tables": tables}, indent=2))


# --- Writing tables ---

SNAPSHOT_TABLES = ("trials", "trial_derived", "sponsor_cik", "filings", "publications")
SCOPE = ("ClinicalTrials.gov industry-sponsored interventional phase 2/3 trials, primary completion 2015-01-01 to "
         "2023-12-31, status TERMINATED/WITHDRAWN/SUSPENDED/COMPLETED")


def write_sec_tables(db: duckdb.DuckDBPyConnection, ciks: list[dict], filings: list[dict]) -> None:
    """(Re)create sponsor_cik and filings. Touches no other table."""
    db.execute("DROP TABLE IF EXISTS sponsor_cik")
    db.execute("CREATE TABLE sponsor_cik (sponsor VARCHAR, cik VARCHAR, ticker VARCHAR, company VARCHAR, match_score DOUBLE)")
    if ciks:
        db.executemany("INSERT INTO sponsor_cik VALUES (?,?,?,?,?)", [[c[k] for k in ("sponsor", "cik", "ticker", "company", "match_score")] for c in ciks])
    db.execute("DROP TABLE IF EXISTS filings")
    db.execute("""CREATE TABLE filings (nct_id VARCHAR, cik VARCHAR, accession VARCHAR, form VARCHAR, filed_date DATE,
        url VARCHAR, matched_terms VARCHAR[], snippet VARCHAR)""")
    if filings:
        db.executemany("INSERT INTO filings VALUES (?,?,?,?,?,?,?,?)",
                       [[f[k] for k in ("nct_id", "cik", "accession", "form", "filed_date", "url", "matched_terms", "snippet")] for f in filings])


def write_snapshot_meta(db: duckdb.DuckDBPyConnection, built_at: dict[str, dt.date]) -> None:
    """(Re)create snapshot_meta with current row counts. built_at says when each table was last built."""
    db.execute("DROP TABLE IF EXISTS snapshot_meta")
    db.execute("CREATE TABLE snapshot_meta (table_name VARCHAR, row_count INTEGER, built_at DATE, scope VARCHAR)")
    for table in SNAPSHOT_TABLES:
        count = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        db.execute("INSERT INTO snapshot_meta VALUES (?,?,?,?)", [table, count, built_at[table], SCOPE])


# --- Main ---


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-sec", action="store_true", help="skip sponsor_cik and filings (no SEC_USER_AGENT)")
    parser.add_argument("--skip-llm", action="store_true", help="keyword rules only for why_stopped_category")
    parser.add_argument("--skip-europepmc", action="store_true", help="skip the Europe PMC fallback")
    args = parser.parse_args()
    today = dt.datetime.now(dt.timezone.utc).date()

    trials, references = fetch_trials()
    derived = derive(trials, today, use_llm=not args.skip_llm)
    stopped_ids = [t["nct_id"] for t in trials if t["overall_status"] in STOPPED]

    links = references + pubmed_si_links(stopped_ids)
    linked = {link["nct_id"] for link in links}
    if not args.skip_europepmc:
        links += europepmc_links([n for n in stopped_ids if n not in linked])
    best: dict[tuple[str, str], dict] = {}
    rank = {"ctgov_result": 0, "pubmed_si": 1, "ctgov_derived": 2, "europepmc_mention": 3}
    for link in links:
        key = (link["nct_id"], link["pmid"])
        if key not in best or rank[link["link_type"]] < rank[best[key]["link_type"]]:
            best[key] = link
    details = pubmed_details(sorted({pmid for _, pmid in best}))
    publications = [
        {**link, **details.get(link["pmid"], {"title": None, "journal": None, "pub_date": None}),
         "url": f"https://pubmed.ncbi.nlm.nih.gov/{link['pmid']}/"}
        for link in best.values()
    ]

    if args.skip_sec or not SEC_USER_AGENT:
        log("SEC steps skipped: set SEC_USER_AGENT to build sponsor_cik and filings")
        ciks, filings = [], []
    else:
        ciks = sponsor_ciks({t["sponsor"] for t in trials if t["sponsor"]})
        log(f"sponsor_cik: {len(ciks)} sponsors matched to a CIK")
        filings = fetch_filings(trials, {c["sponsor"]: c["cik"] for c in ciks})

    DATA_DIR.mkdir(exist_ok=True)
    tmp = DB_PATH.with_suffix(".tmp.duckdb")
    tmp.unlink(missing_ok=True)
    db = duckdb.connect(str(tmp))
    db.execute("""CREATE TABLE trials (nct_id VARCHAR PRIMARY KEY, title VARCHAR, sponsor VARCHAR, sponsor_class VARCHAR,
        phase VARCHAR, conditions VARCHAR[], interventions VARCHAR[], drug_names VARCHAR[], overall_status VARCHAR,
        why_stopped VARCHAR, start_date DATE, primary_completion_date DATE, completion_date DATE, enrollment INTEGER,
        has_results BOOLEAN, results_first_post_date DATE, last_update_date DATE)""")
    db.executemany("INSERT INTO trials VALUES (" + ",".join("?" * 17) + ")", [list(t.values()) for t in trials])
    db.execute("""CREATE TABLE trial_derived (nct_id VARCHAR PRIMARY KEY, results_due_date DATE, results_posted BOOLEAN,
        days_late INTEGER, stopped BOOLEAN, why_stopped_category VARCHAR, why_stopped_method VARCHAR)""")
    db.executemany("INSERT INTO trial_derived VALUES (?,?,?,?,?,?,?)", [list(r.values()) for r in derived])
    write_sec_tables(db, ciks, filings)
    db.execute("""CREATE TABLE publications (nct_id VARCHAR, pmid VARCHAR, link_type VARCHAR, title VARCHAR,
        journal VARCHAR, pub_date DATE, url VARCHAR)""")
    db.executemany("INSERT INTO publications VALUES (?,?,?,?,?,?,?)",
                   [[p[k] for k in ("nct_id", "pmid", "link_type", "title", "journal", "pub_date", "url")] for p in publications])
    write_snapshot_meta(db, {table: today for table in SNAPSHOT_TABLES})
    write_mappings(db)
    db.close()
    tmp.replace(DB_PATH)
    log(f"built {DB_PATH} ({DB_PATH.stat().st_size / 1e6:.1f} MB) and {MAPPINGS_PATH.name}")


if __name__ == "__main__":
    main()
