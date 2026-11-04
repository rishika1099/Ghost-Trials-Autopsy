"""Match registry sponsor names to SEC company names."""

import re

from rapidfuzz import fuzz, process

MATCH_THRESHOLD = 92

# Words that differ between how a sponsor registers a trial and how the company files with the SEC.
SUFFIXES = (
    r"\b(incorporated|inc|corp|corporation|co|company|ltd|limited|llc|plc|lp|sa|ag|nv|se|gmbh|ab|as|asa|"
    r"holdings?|group|the|a/s|s\.a|n\.v|k\.k|spa|s\.p\.a|bv|pty|kgaa)\b"
)


def normalize(name: str) -> str:
    name = name.lower().replace("&", " and ")
    name = re.sub(r"[.,()/'\"-]", " ", name)
    name = re.sub(SUFFIXES, " ", name)
    return re.sub(r"\s+", " ", name).strip()


def match_sponsors(sponsors: set[str], companies: dict[str, tuple[str, str]]) -> list[dict]:
    """companies: {SEC title: (cik, ticker)}. Returns one row per matched sponsor, at or above MATCH_THRESHOLD."""
    by_norm = {}
    for title, (cik, ticker) in companies.items():
        by_norm.setdefault(normalize(title), (title, cik, ticker))
    choices = list(by_norm)
    rows = []
    for sponsor in sorted(sponsors):
        norm = normalize(sponsor)
        if len(norm) < 3:
            continue
        best = process.extractOne(norm, choices, scorer=fuzz.token_sort_ratio)
        if best and best[1] >= MATCH_THRESHOLD:
            title, cik, ticker = by_norm[best[0]]
            rows.append({"sponsor": sponsor, "cik": cik, "ticker": ticker, "company": title, "match_score": round(best[1], 1)})
    return rows
