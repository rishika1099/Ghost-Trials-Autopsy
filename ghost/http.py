"""One HTTP client for every source: timeouts, retries with backoff, per-host rate limits, and a disk cache.

The cache key is the full URL plus params, so the snapshot builder can be re-run cheaply and live
lookups during a request are fast the second time.
"""

import hashlib
import json
import os
import tempfile
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


RETRY_STATUS = (429, 500, 502, 503, 504)


class _Retryable(Exception):
    """A failure worth another try: a network error, a rate limit or a server error."""


def _read_cache(path):
    """(hit, body). A half-written or corrupt file counts as a miss."""
    try:
        return True, json.loads(path.read_text())["body"]
    except (OSError, ValueError, KeyError, TypeError):
        return False, None


def _write_cache(path, record: dict) -> None:
    """Write to a temp file and rename it into place, so a concurrent reader never sees half a file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(record, f)
            os.replace(tmp, path)
        except BaseException:
            os.unlink(tmp)
            raise
    except OSError:
        pass  # a cache we can't write is not worth failing the request over


def get(url: str, params: dict | None = None, *, as_json: bool = True, use_cache: bool = True):
    """GET url and return parsed JSON (or text).

    Retries (with backoff, up to MAX_RETRIES tries) only what can succeed on a second try: network errors,
    429 and 5xx. Anything else (a missing SEC_USER_AGENT, a 400 or 403) raises SourceError at once.
    """
    host = urlparse(url).netloc
    if host == "eutils.ncbi.nlm.nih.gov" and NCBI_API_KEY:
        params = {**(params or {}), "api_key": NCBI_API_KEY}
    path = _cache_path(url, {k: v for k, v in (params or {}).items() if k != "api_key"})
    if use_cache and path.exists():
        hit, body = _read_cache(path)
        if hit:
            return body

    headers = _headers(host)  # raises SourceError right away if SEC_USER_AGENT is missing
    last_error = None
    for attempt in range(MAX_RETRIES):
        _wait_turn(host)
        try:
            try:
                response = _client.get(url, params=params, headers=headers)
            except httpx.HTTPError as e:
                raise _Retryable(f"{type(e).__name__}: {e}") from e
            if response.status_code == 404:
                body = None if as_json else ""
                break
            if response.status_code in RETRY_STATUS:
                raise _Retryable(f"{host} returned {response.status_code}")
            if response.status_code >= 400:
                raise SourceError(f"{host} returned {response.status_code}")
            try:
                body = response.json() if as_json else response.text
            except ValueError as e:
                raise SourceError(f"{host} returned a body that is not JSON") from e
            break
        except _Retryable as e:
            last_error = e
            if attempt + 1 < MAX_RETRIES:
                time.sleep(1.5 * 2**attempt)
    else:
        raise SourceError(f"{host} failed after {MAX_RETRIES} tries: {last_error}")

    if use_cache:
        _write_cache(path, {"url": url, "params": params, "body": body})
    return body
