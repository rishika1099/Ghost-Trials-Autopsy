"""Sort the free-text why_stopped reason into a category: keyword rules first, then one LLM pass for the rest."""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import litellm

from ghost.config import CACHE_DIR, RESEARCHER_MODEL as LABEL_MODEL, VERTEX_LOCATION

LABEL_CACHE = CACHE_DIR.parent / "why_stopped_llm.json"

CATEGORIES = ("safety", "efficacy", "business/strategic", "enrollment", "other", "blank")

# Order matters: the first rule that matches wins. Safety beats efficacy beats business beats enrollment.
RULES = [
    ("safety", r"safety|adverse|toxicit|death|serious|side effect|hepat|risk.benefit|benefit.risk|dsmb.*(safety|concern)|clinical hold"),
    ("efficacy", r"efficacy|futility|futile|lack of (effect|benefit|response)|primary endpoint|interim analys|did not meet (its |the )?(primary )?(endpoint|objective)|ineffective|no benefit|insufficient (effect|activity)"),
    ("business/strategic", r"business|strateg|commercial|portfolio|priorit|funding|financ|sponsor decision|company decision|acquisition|merger|resource|development program|program (was )?(discontinued|terminated)|decision of the sponsor|sponsor('s)? decision"),
    ("enrollment", r"enrol|recruit|accrual|accru|participants? (were|was) not|slow|feasib"),
]
RULES = [(category, re.compile(pattern, re.IGNORECASE)) for category, pattern in RULES]


def classify_why_stopped(reason: str | None) -> tuple[str, str]:
    """-> (category, method). method is keyword, blank, or unmatched (left for the LLM pass)."""
    if not reason or not reason.strip():
        return "blank", "blank"
    for category, pattern in RULES:
        if pattern.search(reason):
            return category, "keyword"
    return "other", "unmatched"


def _label_batch(batch: dict[str, str], allowed: list[str]) -> dict[str, str]:
    prompt = (
        "Each value is the reason a sponsor gave for stopping a clinical trial. Label each with exactly one of "
        f"{allowed}. Use 'other' when none fits (for example COVID-19 disruption or a protocol change). "
        "Return a JSON object mapping each key to its label.\n\n" + json.dumps(batch)
    )
    response = litellm.completion(
        model=LABEL_MODEL, vertex_location=VERTEX_LOCATION, timeout=60, num_retries=1,
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
