"""Registry reason vs. 8-K language: deterministic keyword rules, so every label can be traced to the words
that produced it.

For each stopped trial and each 8-K the snapshot linked to it, we take the snippet's sentences that name the
trial or its drug (plus the sentence after, where reasons often sit), and sort each one:

- reason category, with 8-K specific rules: efficacy means a failure ("did not meet the primary endpoint",
  "futility"), never a mention of an endpoint; safety means a concern ("clinical hold", "safety signal"),
  never "a favorable safety profile"; positive means a success ("met its primary endpoint").
- scope: this_trial (names the NCT ID, or an acronym from the trial's title), other_trial (names a different
  NCT ID or trial acronym: a sentence about another trial of the same drug), or drug_program (only the drug).

A label compares the registry's why_stopped_category with the 8-K categories. A mismatch is a *discrepancy*
between two public statements, never evidence of intent.
"""

import re

METHOD = "keyword_rules_v1"

SEC_RULES = [
    ("efficacy", re.compile(
        r"did not (?:meet|achieve|reach)\b[^.;]{0,60}?\b(?:end ?points?|objectives?|statistical significance|significance|efficacy)|"
        r"did not (?:demonstrate|show)\b[^.;]{0,60}?\b(?:efficacy|benefit|improvement|significan|difference|effect)|"
        r"fail(?:ed|s)? to (?:meet|achieve|reach)\b[^.;]{0,60}?\b(?:end ?points?|objectives?|significance)|"
        r"fail(?:ed|s)? to (?:demonstrate|show)\b[^.;]{0,60}?\b(?:efficacy|benefit|improvement|significan|difference|effect)|"
        r"end ?points?\b[^.;]{0,80}?\bnot (?:achieved|met)|"
        r"futility|lack of (?:efficacy|benefit|effect)|not statistically significant|no statistically significant|"
        r"unlikely to (?:meet|achieve|succeed|demonstrate)|insufficient (?:efficacy|activity)", re.I)),
    ("safety", re.compile(
        r"clinical hold|safety (?:concern|signal|issue|finding)s?|serious adverse (?:event|reaction)s? (?:led|leading|that led|related)|"
        r"(?:patient|participant|subject) deaths?|deaths? (?:of|in) (?:a |two |three )?(?:patient|participant|subject)|"
        r"unacceptable (?:toxicity|safety)|dose-limiting toxicit", re.I)),
    ("business/strategic", re.compile(
        r"strategic (?:decision|reasons?|review|prioriti\w*|realignment|reassessment|options|alternatives)|reprioriti|"
        r"prioriti[sz](?:e|ed|ing|ation)\b|portfolio (?:prioriti\w*|review|decision)|business (?:decision|reasons)|"
        r"lack of funding|(?:due to|because of|limited) (?:funding|financial resources|capital)|conserve (?:cash|capital|resources)|"
        r"extend (?:our |its )?cash runway|restructur\w*|wind(?:ing)? down|commercial (?:viability|considerations|reasons)|"
        r"focus (?:our|its) (?:resources|efforts|development)", re.I)),
    ("enrollment", re.compile(
        r"slow(?:er than expected)? enrol+ment|enrol+ment (?:challenges|difficult\w*|was slow|rate|expectations)|"
        r"did not meet enrol+ment|difficult(?:y|ies) (?:enrol+ing|recruiting)|(?:low|slow|poor) (?:recruitment|accrual)|"
        r"closed to enrol+ment", re.I)),
    ("positive", re.compile(
        r"met (?:its|the|both)(?: \w+)? primary (?:efficacy )?end ?points?|achieved (?:its|the) primary end ?point|"
        r"positive (?:topline|top-line) (?:results|data)", re.I)),
]
# "Not due to safety or efficacy", "without safety concerns": not a reason. Same idea as ghost/classify.py.
NEGATED = re.compile(r"\b(?:not|no|nor|without|unrelated to|neither|rather than)\b[^.;]{0,60}?\b(?:safety|efficacy|futility)\b[^.;]*", re.I)
NCT = re.compile(r"\bNCT\d{8}\b", re.I)
# Trial acronyms: ZEPHYRUS-1, PIVOT IO-001, ENABLAR-2, RESERVOIR. All caps, 4+ characters, maybe a number.
ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{3,}(?:[- ][A-Z]{0,4}-?\d{1,3})?\b")
NOT_ACRONYMS = {"NASDAQ", "NYSE", "GLOBE", "NEWSWIRE", "PHASE", "FDA", "COVID", "SARS", "HIV", "EX-99", "EXHIBIT", "INC", "LLC",
                "CORP", "USA", "IND", "NDA", "BLA", "EMA", "DSMB", "IDMC", "ORR", "MSS", "CEO", "CFO", "GAAP", "OTC", "PRNEWSWIRE",
                "BUSINESS", "WIRE", "ACCESSWIRE", "SEC", "MD", "PHD", "AND", "THE", "FOR", "WITH"}
# Sentence breaks in press-release text, including the dash-separated bullets of a headline.
BREAKS = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\u201c\"])|\s+[\u2013\u2014]\s+|\s*[\u2022\u25aa\u25e6]\s*")
MAX_QUOTE = 400
STRONG_REASONS = {"efficacy", "safety"}


def sentences(text: str) -> list[str]:
    return [s.strip(" \u2013\u2014\u2022") for s in BREAKS.split(text or "") if len(s.strip()) > 15]


def acronyms(text: str) -> set[str]:
    """Trial-name acronyms: 5+ capital letters (EMBOLD, RESERVOIR), or 3+ with a hyphenated number (ENABLAR-2,
    PIVOT IO-001). Biomarkers such as HER2, CD20 or TP53 are not trial names."""
    found = set()
    for a in ACRONYM.findall(text or ""):
        head = re.match(r"[A-Z]+", a).group(0)
        if a.split("-")[0].split(" ")[0] in NOT_ACRONYMS:
            continue
        if len(head) >= 5 or (len(head) >= 3 and re.search(r"-\d", a)):
            found.add(a)
    return found


def categories(sentence: str) -> list[str]:
    cleaned = NEGATED.sub(" ", sentence)
    return [name for name, pattern in SEC_RULES if pattern.search(cleaned)]


def scope(sentence: str, nct_id: str, title: str) -> str:
    ids = {m.upper() for m in NCT.findall(sentence)}
    if nct_id.upper() in ids:
        return "this_trial"
    ours = acronyms(title)
    named = acronyms(sentence)
    if ours & named:
        return "this_trial"
    near_trial_words = {a for a in named if re.search(rf"{re.escape(a)}\W+(?:\w+\W+){{0,5}}?(?:trial|study)|(?:trial|study)\W+(?:\w+\W+){{0,2}}?{re.escape(a)}", sentence, re.I)}
    if ids or near_trial_words:
        return "other_trial"
    return "drug_program"


def quote_of(sentence: str, category: str) -> str:
    """The sentence, cut to MAX_QUOTE characters around the words that set its category. Always an exact
    substring of the filing text."""
    if len(sentence) <= MAX_QUOTE:
        return sentence
    pattern = dict(SEC_RULES)[category]
    match = pattern.search(sentence)
    at = match.start() if match else 0
    start = max(0, at - MAX_QUOTE // 2)
    return sentence[start : start + MAX_QUOTE].strip()


def reason_sentences(snippet: str, nct_id: str, title: str, terms: list[str]) -> list[dict]:
    """Sentences of a snippet that name the trial or its drug, or follow one that does, with a reason category."""
    found = []
    split = sentences(snippet)
    keys = [nct_id.lower()] + [t.lower() for t in terms if t]
    for i, sentence in enumerate(split):
        here = any(k in sentence.lower() for k in keys)
        after = i > 0 and any(k in split[i - 1].lower() for k in keys)
        if not (here or after):
            continue
        cats = categories(sentence)
        if cats:
            where = scope(sentence if here else split[i - 1] + " " + sentence, nct_id, title)
            found.append({"sentence": sentence, "categories": cats, "scope": where, "names_drug": here})
    return found


def label(registry_category: str, sec_categories: set[str]) -> tuple[str, str]:
    """-> (label, rule). Labels: discrepancy, consistent, registry_blank_8k_reason, different_reason, no_reason_in_8k."""
    r = registry_category
    if not sec_categories:
        return "no_reason_in_8k", "8-K sentences give no reason"
    if r in sec_categories:
        return "consistent", f"registry {r}; 8-K also {r}"
    if r == "blank":
        return "registry_blank_8k_reason", f"registry blank; 8-K {'/'.join(sorted(sec_categories))}"
    strong = sec_categories & STRONG_REASONS
    if strong and r not in STRONG_REASONS:
        return "discrepancy", f"registry {r}; 8-K {'/'.join(sorted(strong))}"
    if "safety" in sec_categories and r == "efficacy":
        return "discrepancy", "registry efficacy; 8-K safety"
    if "positive" in sec_categories and r == "efficacy":
        return "discrepancy", "registry efficacy; 8-K reports a positive result"
    if r in STRONG_REASONS and sec_categories & {"business/strategic", "enrollment"} and not strong:
        return "discrepancy", f"registry {r}; 8-K {'/'.join(sorted(sec_categories & {'business/strategic', 'enrollment'}))}"
    return "different_reason", f"registry {r}; 8-K {'/'.join(sorted(sec_categories))}"


def strength(lbl: str, rule: str, where: str, relevance: str | None, registry_reason: str, days_from_stop: int | None) -> int:
    """0 to 10: how strong a discrepancy is for a reader. Only discrepancies score above 0."""
    if lbl != "discrepancy" or where == "other_trial":
        return 0
    # The 8-K gives the strong reason (efficacy, safety) the registry does not: the headline case. The reverse
    # (registry efficacy, 8-K mentions a restructuring) is usually company news, not this trial's stop reason.
    score = 3 if ("efficacy" in rule.split(";")[1] or "safety" in rule.split(";")[1]) else 0
    score += {"this_trial": 3, "drug_program": 1}.get(where, 0)
    score += 1 if relevance == "nct_id" else 0
    sec_side = rule.split(";")[1]
    for reason in ("safety", "efficacy"):
        if reason in sec_side and re.search(rf"\bnot\b[^.;]{{0,60}}\b{reason}\b", registry_reason or "", re.I):
            score += 2  # the registry explicitly rules out the reason the 8-K gives
            break
    if days_from_stop is not None and days_from_stop <= 60:
        score += 1
    if "efficacy" not in sec_side and "safety" not in sec_side:
        score = min(score, 2)  # the reverse direction never outranks an 8-K that gives efficacy or safety
    return min(score, 10)


# Rows a person checked by reading the filing (Phase 4 review, 2026-11-04). Each quote was confirmed to be an
# exact substring of the filing's text. They replace the keyword row for the same trial and filing, or are
# added when the filing is not among the snapshot's three per trial. rule says what the reader found.
HAND_CHECKED = [
    {"nct_id": "NCT03980730", "accession": "0001564590-21-008154", "filed_date": "2021-02-24",
     "filing_url": "https://www.sec.gov/Archives/edgar/data/1641489/000156459021008154/vtvt-ex991_6.htm",
     "sec_quote": "On December 15, 2020, vTv announced that the phase 2 Elevage Study of azeliragon did not meet its primary objective.",
     "sec_categories": ["efficacy"], "scope": "this_trial", "label": "discrepancy", "strength": 9,
     "rule": "registry business/strategic ('for business reasons'); 8-K names this trial (Elevage, the registry acronym) and says it did not meet its primary objective"},
    {"nct_id": "NCT05528861", "accession": "0000950170-24-004686", "filed_date": "2024-01-16",
     "filing_url": "https://www.sec.gov/Archives/edgar/data/1564824/000095017024004686/allk-ex99_2.htm",
     "sec_quote": "Allakos Announces Phase 2 Lirentelimab Trials in Atopic Dermatitis and Chronic Spontaneous Urticaria Did Not Meet Their Primary Endpoints",
     "sec_categories": ["efficacy"], "scope": "this_trial", "label": "discrepancy", "strength": 9,
     "rule": "registry business/strategic ('No longer pursuing development'); 8-K names this trial (MAVERICK, the chronic spontaneous urticaria trial) and says it did not meet its primary endpoint"},
    {"nct_id": "NCT02227784", "accession": "0000059478-15-000173", "filed_date": "2015-10-22",
     "filing_url": "https://www.sec.gov/Archives/edgar/data/59478/000005947815000173/q315lillysalesandearningsp.htm",
     "sec_quote": "The company will terminate the Phase III trials of evacetrapib for the treatment of high-risk atherosclerotic cardiovascular disease due to insufficient efficacy.",
     "sec_categories": ["efficacy"], "scope": "this_trial", "label": "discrepancy", "strength": 8,
     "rule": "registry business/strategic ('Study termination due to program termination'); 8-K says the evacetrapib Phase III trials, which include this one (ACCENTUATE), stop due to insufficient efficacy"},
    {"nct_id": "NCT04802837", "accession": "0001599298-22-000114", "filed_date": "2022-10-20",
     "filing_url": "https://www.sec.gov/Archives/edgar/data/1599298/000159929822000114/a2022_prx1020xidweek2022re.htm",
     "sec_quote": "Ridinilazole achieved a numerically higher sustained clinical response rate (73.0% vs 70.7%) than vancomycin, but did not achieve the pre-specified superiority endpoint",
     "sec_categories": ["efficacy"], "scope": "drug_program", "label": "discrepancy", "strength": 6,
     "rule": "registry business/strategic (stopped to pursue development with a partner); the 8-K result is from the ridinilazole Phase 3 program, not this adolescent study (Ri-CoDIFy 3)"},
    {"nct_id": "NCT02452528", "accession": "0001193125-16-764656", "filed_date": "2016-11-10",
     "filing_url": "https://www.sec.gov/Archives/edgar/data/879407/000119312516764656/d290694dex991.htm",
     "sec_quote": "The study is on hold while the company provides responses to questions arising from a nonclinical toxicology study in non-human primates",
     "sec_categories": ["safety"], "scope": "drug_program", "label": "discrepancy", "strength": 6,
     "rule": "registry business/strategic ('Company decision to discontinue trial'); 8-K reports an FDA clinical hold on the ARC-520 study Heparc-2004 over a nonclinical toxicology study; the registry does not say which NCT ID is Heparc-2004"},
    {"nct_id": "NCT05181995", "accession": "0001104659-23-039151", "filed_date": "2023-03-30",
     "filing_url": "https://www.sec.gov/Archives/edgar/data/1674365/000110465923039151/tm2311035d1_ex99-1.htm",
     "sec_quote": "The study was halted in February prior to its completion in support of the company’s preservation of capital.",
     "sec_categories": ["business/strategic"], "scope": "this_trial", "label": "consistent", "strength": 0,
     "rule": "registry business/strategic ('company decision'); 8-K says the PTSD study was halted to preserve capital; its later analysis missing the primary endpoint is a result, not the stop reason"},
    {"nct_id": "NCT05065411", "accession": "0001193125-24-133757", "filed_date": "2024-05-08",
     "filing_url": "https://www.sec.gov/Archives/edgar/data/863894/000119312524133757/d820381dex991.htm",
     "sec_quote": "subject to the availability of sufficient funding, Phase 3 ENABLAR-2 clinical trial of enobosarm and abemaciclib",
     "sec_categories": ["business/strategic"], "scope": "this_trial", "label": "consistent", "strength": 0,
     "rule": "registry business/strategic ('Business decision'); no Veru 8-K from 2023-10 to 2025-06 that names ENABLAR-2 gives an efficacy or safety reason; they make the trial subject to funding"},
]
