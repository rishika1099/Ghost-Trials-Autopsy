"""Deterministic checks the Citation Checker runs on every claim before the model pass.

They catch three kinds of error with certainty, so the result does not depend on the model:
- a quote that is not in the cited records, character for character (case, curly quotes and spacing aside);
- a date that is in none of the cited records;
- an overreaching word ("hid", "concealed", "misled", "broke the law"): a mismatch between sources is a
  discrepancy, never proof of intent or illegality.
Anything subtler (a wrong status, a misread reason, a wrong number) is left to the model pass.
"""

import calendar
import json
import re

MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
LONG_DATE = re.compile(r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.? (\d{1,2}),? (\d{4})\b", re.I)
MONTH_YEAR = re.compile(r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.? (\d{4})\b", re.I)
QUOTED = re.compile(r"[\"“]([^\"“”]+)[\"”]")
MIN_QUOTE_WORDS = 3
OVERREACH = re.compile(
    r"\b(hid|hide|hides|hiding|hidden|conceal\w*|cover(?:ed|ing)?[- ]up|mislead\w*|misled|lied|lies|lying|deceiv\w*|"
    r"deception|deceptive|fraud\w*|illegal\w*|unlawful\w*|broke the law|break(?:s|ing)? the law|violat\w* (?:the )?law|"
    r"withh[eo]ld\w*|buried|bury|suppress\w*|secretly|covert\w*|whitewash\w*)\b", re.I)
# "A mismatch is not evidence that the company hid anything" is allowed: the word is negated.
NEGATION_BEFORE = re.compile(r"\b(not|no|never|cannot|can't|without|nor)\b[^.;]{0,50}$", re.I)


def _norm(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip().casefold()


def record_text(records: list[dict]) -> str:
    """Every string in the cited records (title and data), as one normalized block."""
    parts = []
    for record in records:
        parts.append(str(record.get("title") or ""))
        parts.append(json.dumps(record.get("data") or {}, default=str, ensure_ascii=False))
    return _norm(" ".join(parts).replace("\\n", " ").replace('\\"', '"'))


def dates_in(text: str) -> set[str]:
    """ISO dates (YYYY-MM-DD) and months (YYYY-MM) named in text, in any of the usual forms."""
    found = {f"{y}-{m}-{d}" for y, m, d in ISO_DATE.findall(text)}
    found |= {f"{y}-{MONTHS[m.lower()]:02d}-{int(d):02d}" for m, d, y in LONG_DATE.findall(text)}
    without_days = LONG_DATE.sub(" ", text)
    found |= {f"{y}-{MONTHS[m.lower()]:02d}" for m, y in MONTH_YEAR.findall(without_days)}
    return found


def quote_problems(claim: str, pool: str) -> list[str]:
    problems = []
    for quote in QUOTED.findall(claim):
        if len(quote.split()) < MIN_QUOTE_WORDS:
            continue  # a quoted term ("Business decision") is checked with the rest of the facts by the model
        pieces = [p.strip(" .,;:") for p in re.split(r"\.\.\.|…|\[\.\.\.\]", quote) if p.strip(" .,;:")]
        if not all(_norm(p) in pool for p in pieces):
            problems.append(f'quote not in the cited records: "{quote}"')
    return problems


def date_problems(claim: str, pool_dates: set[str]) -> list[str]:
    problems = []
    for date in sorted(dates_in(claim)):
        if date in pool_dates or (len(date) == 7 and any(d.startswith(date) for d in pool_dates)):
            continue
        problems.append(f"date {date} is in none of the cited records")
    return problems


def overreach_problems(claim: str) -> list[str]:
    problems = []
    for match in OVERREACH.finditer(claim):
        if NEGATION_BEFORE.search(claim[: match.start()]):
            continue
        problems.append(f'overreaching word "{match.group(0)}": a mismatch is a discrepancy, not proof of intent or illegality')
    return problems


def check_claim(claim: str, records: list[dict]) -> list[str]:
    """Problems with one claim against the records it cites. Empty means the rules found nothing wrong."""
    pool = record_text(records)
    raw = " ".join([str(r.get("title") or "") + " " + json.dumps(r.get("data") or {}, default=str, ensure_ascii=False) for r in records])
    return quote_problems(claim, pool) + date_problems(claim, dates_in(raw)) + overreach_problems(claim)
