"""Sort the free-text why_stopped reason into a category: keyword rules first, then one LLM pass for the rest."""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import litellm

from ghost.config import CACHE_DIR, RESEARCHER_MODEL as LABEL_MODEL, VERTEX_ARGS

LABEL_CACHE = CACHE_DIR.parent / "why_stopped_llm.json"

CATEGORIES = ("safety", "efficacy", "business/strategic", "enrollment", "other", "blank")

# Order matters: the first rule that matches wins. Safety beats efficacy beats business beats enrollment.
RULES = [
    ("safety", r"safety|adverse|toxicit|death|serious|side effect|hepat|risk.benefit|benefit.risk|dsmb.*(safety|concern)|clinical hold"),
    ("efficacy", r"efficacy|futility|futile|lack of (effect|benefit|response)|primary endpoint|interim analys|did not meet (its |the )?(primary )?(endpoint|objective)|ineffective|no benefit|insufficient (effect|activity)"),
    ("business/strategic", r"business|strateg|commercial|portfolio|priorit|funding|financ|sponsor decision|company decision|acquisition|merger|resource|development program|program (was )?(discontinued|terminated)|decision (of|by) the (sponsor|company)|sponsor('s)? decision|administrative|management decision"),
    ("enrollment", r"enrol|recruit|accrual|accru|participants? (were|was) not|slow|feasib"),
]
RULES = [(category, re.compile(pattern, re.IGNORECASE)) for category, pattern in RULES]


# "Not due to safety or efficacy concerns" must not count as safety, and a "Data Safety Monitoring Board"
# is a committee, not a reason. Remove both before matching.
NEGATED = re.compile(r"\b(not|no|nor|non|without|unrelated to|neither|rather than)\b[^.;]{0,80}?\b(safety|efficacy|feasibility|futility|tolerability)\b[^.;]*", re.IGNORECASE)
BOARDS = re.compile(r"\b(data (and )?safety monitoring (board|committee)|safety (review|monitoring) (board|committee)|dsmb|idmc|dmc)\b", re.IGNORECASE)


# "Canceled before enrollment" says when it stopped, not why.
BEFORE_ENROLLING = re.compile(r"\b(before|prior to)\s+(any\s+)?(participants?|patients?|subjects?)?\s*(were\s+|was\s+)?(enrol\w*|recruit\w*|dosed|randomi[sz]ed)", re.IGNORECASE)


# "Safety" as data being collected, or as a finding that was absent, is not the reason a trial stopped:
# "sufficient safety data has been generated", "followed for safety data", "to analyze available safety and
# efficacy data", "absence of significant safety findings". "Review of safety data" is left alone: it is a reason.
SAFETY_AS_DATA = re.compile(
    r"\b(sufficient|considerable|enough|additional|available|accumulated|cumulative)\s+safety\s+(data|information)\b"
    r"|\bfollow(ed|ed up|-up)?\s+(up\s+)?(\w+\s+){0,2}for\s+(long.term\s+)?safety\b"
    r"|\b(obtain|collect|analy[sz]e|evaluate|gather)\w*\b[^.;*]{0,40}?\b(safety|efficacy)\b[^.;*]{0,30}?\b(data|future)\b"
    r"|\b(safety|efficacy)\s+data\s+(has\s+been\s+|have\s+been\s+|was\s+|were\s+)?(generated|gathered|collected)\b"
    r"|\bbased\s+on\s+the\s+safety\s+data\s+gathered\b"
    r"|\b(absence|lack|free)\s+of\s+((any|significant|new|major|clinically|relevant|meaningful)\s+)*safety\s+(findings|concerns|signals|issues)\b"
    r"|\bsafety\s+data\s+demonstrated\b[^.;]*"
    r"|\bbeneficial\s+safety\s+information\b",
    re.IGNORECASE,
)


def _clean(reason: str) -> str:
    text = BOARDS.sub(" monitoring board ", reason)
    text = SAFETY_AS_DATA.sub(" ", text)
    return NEGATED.sub(" ", BEFORE_ENROLLING.sub(" ", text))


def classify_why_stopped(reason: str | None) -> tuple[str, str]:
    """-> (category, method). method is keyword, blank, or unmatched (left for the LLM pass)."""
    if not reason or not reason.strip():
        return "blank", "blank"
    text = _clean(reason)
    for category, pattern in RULES:
        if pattern.search(text):
            return category, "keyword"
    return "other", "unmatched"


def _label_batch(batch: dict[str, str], allowed: list[str]) -> dict[str, str]:
    prompt = (
        "Each value is the reason a sponsor gave for stopping a clinical trial. Label each with exactly one of "
        f"{allowed}. Use 'other' when none fits (for example COVID-19 disruption or a protocol change). "
        "Use 'safety' only when a safety problem or concern is why it stopped: enough safety data having been "
        "collected, or an absence of safety findings, is not 'safety'. "
        "Return a JSON object mapping each key to its label.\n\n" + json.dumps(batch)
    )
    response = litellm.completion(
        model=LABEL_MODEL, **VERTEX_ARGS, timeout=60, num_retries=1,
        messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"},
    )
    parsed = json.loads(response.choices[0].message.content)
    return {k: v for k, v in parsed.items() if k in batch and v in allowed}


def llm_classify(reasons: dict[str, str], batch_size: int = 40) -> dict[str, str]:
    """{nct_id: reason} -> {nct_id: category} for the reasons the rules missed. Batches run in parallel;
    a batch that fails keeps its keyword label. Labels are cached by reason text."""
    cached = json.loads(LABEL_CACHE.read_text()) if LABEL_CACHE.exists() else {}
    labels: dict[str, str] = {k: cached[v] for k, v in reasons.items() if v in cached}
    items = [(k, v) for k, v in reasons.items() if v not in cached]
    allowed = [c for c in CATEGORIES if c != "blank"]
    batches = [dict(items[i : i + batch_size]) for i in range(0, len(items), batch_size)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_label_batch, b, allowed): b for b in batches}
        for future in as_completed(futures):
            batch = futures[future]
            try:
                new = future.result()
            except Exception as e:  # the keyword labels still stand
                print(f"llm_classify: a batch failed: {type(e).__name__}: {str(e)[:200]}", flush=True)
                continue
            labels.update(new)
            cached.update({batch[k]: v for k, v in new.items()})
            LABEL_CACHE.parent.mkdir(parents=True, exist_ok=True)
            LABEL_CACHE.write_text(json.dumps(cached))
    return labels
