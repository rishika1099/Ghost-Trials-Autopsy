"""Match registry sponsor names to SEC company names.

A sponsor matches an SEC company only when all of these hold:
1. Their *core* names are identical (spaces ignored). The core is what is left after dropping legal suffixes
   and generic industry words ("Pharmaceuticals", "Therapeutics", "Bio"). Fuzzy scoring on whole names let a
   shared generic word carry unrelated companies over the threshold ("AFT Pharmaceuticals" scored 92.3
   against "Atea Pharmaceuticals"), and fuzzy scoring on cores still paired different companies one letter
   apart ("Athenex" / "Athene", "Akero" / "Keros"), so neither is used.
2. Their industry words do not contradict each other (see `compatible`).
3. If the core is ambiguous (it appears in several SEC titles, like "united" or "edison"), the full names
   must also match closely.
4. If a SIC lookup is given, the SEC company's industry code is a health one (drugs, biologics, devices,
   research). This keeps "Edison Pharmaceuticals" off "Edison International" and "Meridian Bioscience" off
   "Meridian Corp".
A short override list covers subsidiaries whose parent files the 8-Ks (Janssen -> Johnson & Johnson).
"""

import re
import unicodedata
from collections.abc import Callable

from rapidfuzz import fuzz

MATCH_THRESHOLD = 92
# Core names shorter than this are too weak on their own: the industries must agree too.
SHORT_CORE = 6

# Words that differ between how a sponsor registers a trial and how the company files with the SEC.
SUFFIXES = (
    r"\b(incorporated|inc|corp|corporation|co|company|ltd|limited|llc|plc|lp|sa|ag|nv|se|gmbh|ab|as|asa|"
    r"holdings?|group|the|a/s|s\.a|n\.v|k\.k|kk|spa|s\.p\.a|srl|bv|bvba|uc|pty|kgaa|adr)\b"
)
# Industry and place words that say little about which company it is.
GENERIC = (
    r"\b(pharmaceuticals?|pharma|pharmaceutica|therapeutics?|biosciences?|biopharm|biopharma|biopharmaceuticals?|"
    r"biotech|biotechnology|biologics|bio|biotherapeutics|medicines?|sciences?|life|laboratories|labs?|"
    r"oncology|research|development|and|r|d|us|usa|america|uk|aus|international|global)\b"
)
# SEC titles often end in a state or country tag: "HERON THERAPEUTICS, INC. /DE/", "VERTEX PHARMACEUTICALS INC / MA".
STATE_TAG = r"\s*/\s*[a-z]{2,3}\s*/?\s*$"

# Industry families. Two names that both state an industry must share one.
INDUSTRIES = {
    "bio": r"\b(pharma\w*|therapeutics?|bio\w*|medicines?|oncology|laboratories|labs?|sciences?|genetics|genomics|vaccines?|immun\w*)\b",
    "tech": r"\b(technolog\w*|solutions|software|semiconductor\w*)\b",
}

# SEC industry codes for companies that run drug trials: drugs and biologics, consumer health (soap,
# cosmetics), diagnostics, devices, ophthalmic goods, drug wholesale, health plans, health services, and
# commercial research labs. An empty code means an unsponsored ADR listing that files nothing with SEC.
HEALTH_SIC = {"2833", "2834", "2835", "2836", "2840", "2844", "3826", "3841", "3842", "3843", "3844", "3845", "3851",
              "5047", "5122", "6324", "8731"}
ADR_SIC = "8880"  # 'American Depositary Receipts': says nothing about the industry, so the names must


def is_health_sic(sic: str | None) -> bool:
    return bool(sic) and (sic in HEALTH_SIC or sic.startswith("80"))


# Subsidiaries that register trials under their own name while the parent files the 8-Ks.
# Keyed by core name prefix; each CIK checked against SEC's company list. Kept small on purpose.
OVERRIDES = {
    "merck sharp dohme": ("0000310158", "MRK", "Merck & Co., Inc."),
    "janssen": ("0000200406", "JNJ", "JOHNSON & JOHNSON"),
    "teva": ("0000818686", "TEVA", "TEVA PHARMACEUTICAL INDUSTRIES LTD"),
}


def _fold(name: str) -> str:
    """Lowercase ASCII: 'Daré' -> 'dare'."""
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()


def normalize(name: str) -> str:
    name = _fold(name)
    name = re.sub(STATE_TAG, " ", name)
    name = name.replace("&", " and ").replace("'", "")
    name = re.sub(r"[.,()/\"-]", " ", name)
    name = re.sub(SUFFIXES, " ", name)
    return re.sub(r"\s+", " ", name).strip()


def core_name(name: str) -> str:
    """The distinctive part of a company name: 'Heron Therapeutics, Inc. /DE/' -> 'heron'."""
    return re.sub(r"\s+", " ", re.sub(GENERIC, " ", normalize(name))).strip()


def core_key(name: str) -> str:
    """The core with spaces removed, so 'Dr. Reddy's' and 'DR REDDYS' agree."""
    return core_name(name).replace(" ", "")


def industries(name: str) -> set[str]:
    folded = _fold(name)
    return {family for family, pattern in INDUSTRIES.items() if re.search(pattern, folded)}


def compatible(sponsor: str, title: str) -> bool:
    """Same company as far as the industry words can tell."""
    ours, theirs = industries(sponsor), industries(title)
    if ours and theirs:
        return bool(ours & theirs)
    if len(core_key(sponsor)) < SHORT_CORE:
        return ours == theirs  # a short core alone ('arena') is too weak: the industries must agree too
    return True


def full_score(a: str, b: str) -> float:
    return round(fuzz.token_sort_ratio(normalize(a), normalize(b)), 1)


def override_for(sponsor: str) -> tuple[str, str, str] | None:
    core = core_name(sponsor)
    for prefix, target in OVERRIDES.items():
        if core == prefix or core.startswith(prefix + " "):
            return target
    return None


class CompanyIndex:
    """SEC companies grouped by core key, plus how many titles each core word appears in."""

    def __init__(self, companies: dict[str, tuple[str, str]]):
        self.by_core: dict[str, list[tuple[str, str, str]]] = {}
        self.word_count: dict[str, int] = {}
        for title, (cik, ticker) in companies.items():
            key = core_key(title)
            if key:
                self.by_core.setdefault(key, []).append((title, cik, ticker))
            for word in set(normalize(title).split()):
                self.word_count[word] = self.word_count.get(word, 0) + 1

    def ambiguous(self, sponsor: str) -> bool:
        """True when the core is a word many SEC titles share ('united', 'edison', 'rocket')."""
        words = core_name(sponsor).split()
        return any(self.word_count.get(w, 0) >= 2 for w in words) and len(words) == 1


def pick(sponsor: str, candidates: list[tuple[str, str, str]], ambiguous: bool,
         sic_lookup: Callable[[str], str | None] | None) -> tuple[str, str, str] | None:
    """The first candidate that passes the industry, ambiguity and SIC checks, best full-name score first."""
    for title, cik, ticker in sorted(candidates, key=lambda c: -full_score(sponsor, c[0])):
        if not compatible(sponsor, title):
            continue
        if ambiguous and full_score(sponsor, title) < MATCH_THRESHOLD:
            continue
        if sic_lookup is not None:
            sic = sic_lookup(cik)
            both_bio = "bio" in industries(sponsor) and "bio" in industries(title)
            if not (is_health_sic(sic) or (sic == ADR_SIC and both_bio)):
                continue
        return title, cik, ticker
    return None


def match_sponsors(sponsors: set[str], companies: dict[str, tuple[str, str]],
                   sic_lookup: Callable[[str], str | None] | None = None) -> list[dict]:
    """companies: {SEC title: (cik, ticker)}. sic_lookup: cik -> SEC industry code, or None to skip that check.

    Returns one row per matched sponsor. match_score is the full-name similarity (0 to 100); match_method
    says how it matched: override or exact_core."""
    index = CompanyIndex(companies)
    rows = []
    for sponsor in sorted(sponsors):
        override = override_for(sponsor)
        if override:
            cik, ticker, title = override
            rows.append({"sponsor": sponsor, "cik": cik, "ticker": ticker, "company": title,
                         "match_score": full_score(sponsor, title), "match_method": "override"})
            continue
        key = core_key(sponsor)
        if len(key) < 2 or key not in index.by_core:
            continue
        found = pick(sponsor, index.by_core[key], index.ambiguous(sponsor), sic_lookup)
        if found:
            title, cik, ticker = found
            rows.append({"sponsor": sponsor, "cik": cik, "ticker": ticker, "company": title,
                         "match_score": full_score(sponsor, title), "match_method": "exact_core"})
    return rows
