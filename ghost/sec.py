"""SEC EDGAR helpers shared by the snapshot builder and the disclosures tools, so both search the same
date windows and match sponsors the same way."""

import datetime as dt
import html
import re

from ghost import http
from ghost.names import core_key, normalize

EFTS = "https://efts.sec.gov/LATEST/search-index"
TICKERS = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
FILING_WINDOW_DAYS = 120

# Intervention names that are not the sponsor's drug, or too vague to search EDGAR with.
NOT_A_DRUG = re.compile(
    r"^(placebo|matching placebo|saline|vehicle|standard of care|soc|best supportive care|chemotherapy|"
    r"investigator'?s? choice|non-steroidal ai|steroidal ai|aromatase inhibitor|combo|combination|"
    r"control|sham|observation|usual care|treatment)$")


def filing_windows(t: dict) -> list[tuple[dt.date, dt.date]]:
    """FILING_WINDOW_DAYS either side of each anchor date (primary completion, completion, last update),
    merged where they overlap. One window from the earliest to the latest date spanned years when a registry
    record was updated long after the trial stopped."""
    anchors = sorted({d for d in (t.get("primary_completion_date"), t.get("completion_date"), t.get("last_update_date")) if d})
    pad = dt.timedelta(days=FILING_WINDOW_DAYS)
    windows: list[list[dt.date]] = []
    for anchor in anchors:
        if windows and anchor - pad <= windows[-1][1]:
            windows[-1][1] = anchor + pad
        else:
            windows.append([anchor - pad, anchor + pad])
    return [(start, end) for start, end in windows]


def drug_terms(drug_names: list[str], limit: int = 3) -> list[str]:
    """Searchable drug names: 'Enobosarm & Abemaciclib Combo' -> ['Enobosarm', 'Abemaciclib'].
    Splits combinations, drops doses and words like placebo, keeps the registry's order."""
    terms: list[str] = []
    for name in drug_names:
        name = re.sub(r"\([^)]*\)", lambda m: " , " + m.group(0)[1:-1] + " , ", name)  # '(exemestane ...)' is its own part
        for part in re.split(r"\s*(?:&|\+|/|,|;|\bwith or without\b|\bwith\b|\bplus\b|\band\b|\bor\b|\bcombo\b)\s*", name, flags=re.I):
            part = re.sub(r"\b\d+(\.\d+)?\s*(mg|mcg|µg|ug|g|ml|mg/kg|iu|%)\b.*$", "", part, flags=re.I).strip(" .-")
            part = re.sub(r"\b(prefilled syringe|tablets?|capsules?|injection|oral|iv|sc|low dose|high dose)\b", "", part, flags=re.I).strip(" .-")
            if len(part) >= 4 and not NOT_A_DRUG.match(part.lower()) and part.lower() not in (x.lower() for x in terms):
                terms.append(part)
    return terms[:limit]


def plain_text(document: str) -> str:
    """Filing HTML to plain text: tags dropped, entities decoded ('&#8226;' -> '•'), whitespace collapsed."""
    text = re.sub(r"<[^>]+>", " ", document)
    text = html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def sec_profile(cik: str) -> dict:
    """SEC's own record for a filer: industry code, whether it files 8-Ks (foreign issuers file 6-Ks), and
    the date of its latest 8-K."""
    try:
        record = http.get(SUBMISSIONS.format(cik=cik)) or {}
    except http.SourceError:
        return {"sic": None, "files_8k": None, "last_8k": ""}
    recent = record.get("filings", {}).get("recent", {})
    dates_8k = [d for d, form in zip(recent.get("filingDate", []), recent.get("form", [])) if form == "8-K"]
    return {"sic": record.get("sic") or None, "files_8k": bool(dates_8k), "last_8k": max(dates_8k, default="")}


def edgar_entities(sponsor: str) -> dict[str, tuple[str, str]]:
    """EDGAR's company-name search, which also knows delisted filers (current names only). Returns
    {title: (cik, '')} for hits whose core name is the sponsor's."""
    try:
        found = http.get(EFTS, {"keysTyped": normalize(sponsor)})  # every word must appear, so drop 'Inc.', 'LLC'
    except http.SourceError:
        return {}
    entities: dict[str, tuple[str, str]] = {}
    for hit in (found or {}).get("hits", {}).get("hits", [])[:10]:
        title = hit.get("_source", {}).get("entity")
        if title and core_key(title) == core_key(sponsor):
            entities.setdefault(title, (str(hit["_id"]).zfill(10), ""))  # EDGAR ranks the active filer first
    return entities
