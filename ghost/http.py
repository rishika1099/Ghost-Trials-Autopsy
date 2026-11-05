"""One HTTP client for every source: timeouts, retries with backoff, per-host rate limits, and a disk cache.

The cache key is the full URL plus params, so the snapshot builder can be re-run cheaply and live
lookups during a request are fast the second time.
"""

import hashlib
import json
import threading
import time
from urllib.parse import urlparse

import httpx

from ghost.config import CACHE_DIR, NCBI_API_KEY, SEC_USER_AGENT

TIMEOUT_S = 15
MAX_RETRIES = 3
DEFAULT_UA = "GhostTrialsAutopsy/0.1 (Columbia course project; github.com/rishika1099/Ghost-Trials-Autopsy)"

# Requests per second we allow ourselves, per host. SEC asks for under 10 across all its hosts,
# so efts.sec.gov and www.sec.gov share one "sec.gov" budget. NCBI asks for under 3 without a key.
RATE_LIMITS = {
    "sec.gov": 8,
    "eutils.ncbi.nlm.nih.gov": 9 if NCBI_API_KEY else 2.5,
    "www.ebi.ac.uk": 8,
    "clinicaltrials.gov": 8,
    "api.fda.gov": 3,
}

_locks: dict[str, threading.Lock] = {}
_last_call: dict[str, float] = {}
_guard = threading.Lock()
_client = httpx.Client(timeout=TIMEOUT_S, follow_redirects=True)


class SourceError(RuntimeError):
    """A source could not be reached or refused the request. Tools turn this into a JSON error."""


def _rate_key(host: str) -> str:
    return "sec.gov" if host == "sec.gov" or host.endswith(".sec.gov") else host


def _wait_turn(host: str) -> None:
    host = _rate_key(host)
    rate = RATE_LIMITS.get(host)
    if not rate:
        return
    with _guard:
        lock = _locks.setdefault(host, threading.Lock())
    with lock:
        gap = 1.0 / rate - (time.monotonic() - _last_call.get(host, 0.0))
        if gap > 0:
            time.sleep(gap)
        _last_call[host] = time.monotonic()


def _headers(host: str) -> dict:
    if host.endswith("sec.gov"):
        if not SEC_USER_AGENT:
            raise SourceError("SEC_USER_AGENT is not set. SEC requires a contact string with an email.")
        return {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    return {"User-Agent": DEFAULT_UA}


def _cache_path(url: str, params: dict | None):
    key = url + "?" + json.dumps(params or {}, sort_keys=True)
    digest = hashlib.sha256(key.encode()).hexdigest()
    return CACHE_DIR / digest[:2] / f"{digest}.json"


def get(url: str, params: dict | None = None, *, as_json: bool = True, use_cache: bool = True):
    """GET url and return parsed JSON (or text). Raises SourceError after MAX_RETRIES failures."""
    host = urlparse(url).netloc
    if host == "eutils.ncbi.nlm.nih.gov" and NCBI_API_KEY:
        params = {**(params or {}), "api_key": NCBI_API_KEY}
    path = _cache_path(url, {k: v for k, v in (params or {}).items() if k != "api_key"})
    if use_cache and path.exists():
        cached = json.loads(path.read_text())
        return cached["body"]

    last_error = None
    for attempt in range(MAX_RETRIES):
        _wait_turn(host)
        try:
            response = _client.get(url, params=params, headers=_headers(host))
            if response.status_code == 404:
                body = None if as_json else ""
                break
            if response.status_code in (429, 500, 502, 503, 504):
                raise SourceError(f"{host} returned {response.status_code}")
            response.raise_for_status()
            body = response.json() if as_json else response.text
            break
        except (httpx.HTTPError, SourceError, ValueError) as e:
            last_error = e
            time.sleep(1.5 * 2**attempt)
    else:
        raise SourceError(f"{host} failed after {MAX_RETRIES} tries: {type(last_error).__name__}: {last_error}")

    if use_cache:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"url": url, "params": params, "body": body}))
    return body
