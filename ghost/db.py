"""Read-only access to the snapshot, with the guardrails the Text2SQL starter uses."""

import json
import re
import threading

import duckdb

from ghost.config import DB_PATH, MAPPINGS_PATH

MAX_ROWS = 50

_db = None
_lock = threading.Lock()


class SnapshotMissing(RuntimeError):
    pass


def connection() -> duckdb.DuckDBPyConnection:
    global _db
    with _lock:
        if _db is None:
            if not DB_PATH.exists():
                raise SnapshotMissing(f"No snapshot at {DB_PATH}. Run `uv run python scripts/build_snapshot.py`.")
            # The security boundary is the connection, not the prompt: read-only, no file or network access.
            _db = duckdb.connect(str(DB_PATH), read_only=True,
                                 config={"enable_external_access": False, "lock_configuration": True})
        return _db


def mappings() -> dict:
    return json.loads(MAPPINGS_PATH.read_text()) if MAPPINGS_PATH.exists() else {"tables": []}


FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|create|alter|attach|detach|copy|export|import|install|load|pragma|set|call|"
    r"checkpoint|vacuum|grant|revoke|truncate|replace|merge)\b",
    re.IGNORECASE,
)


def check_select(sql: str) -> str | None:
    """None if sql is a single read-only SELECT (or WITH ... SELECT), else the reason it's rejected."""
    stripped = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.DOTALL).strip().rstrip(";").strip()
    if not stripped:
        return "Empty query."
    if ";" in stripped:
        return "Only one statement is allowed."
    if not re.match(r"^(select|with)\b", stripped, re.IGNORECASE):
        return "Only SELECT queries are allowed."
    # Strings can legitimately contain words like 'update': check the query with its literals removed.
    if FORBIDDEN.search(re.sub(r"'(?:[^']|'')*'", "''", stripped)):
        return "Only read-only SELECT queries are allowed."
    if re.search(r"=\s*'NA'", stripped, re.IGNORECASE):
        return "Missing values are NULL, not 'NA'. Use IS NULL / IS NOT NULL."
    return None


def run_select(sql: str, limit: int = MAX_ROWS) -> dict:
    """Run a validated SELECT with an enforced LIMIT. Returns {columns, rows, truncated} or {error}."""
    reason = check_select(sql)
    if reason:
        return {"error": f"Rejected: {reason}"}
    body = re.sub(r"--[^\n]*", " ", sql).strip().rstrip(";")
    wrapped = f"SELECT * FROM ({body}) AS q LIMIT {limit + 1}"
    with connection().cursor() as cursor:
        try:
            cursor.execute(wrapped)
            rows = cursor.fetchall()
        except duckdb.Error as e:
            return {"error": str(e)[:500]}
        columns = [c[0] for c in cursor.description or []]
    return {"columns": columns, "rows": [dict(zip(columns, r)) for r in rows[:limit]], "truncated": len(rows) > limit}


def trial_record(nct_id: str) -> dict | None:
    result = run_select(f"""
        SELECT t.*, d.results_due_date, d.results_posted, d.days_late, d.stopped, d.why_stopped_category, d.why_stopped_method
        FROM trials t JOIN trial_derived d USING (nct_id) WHERE t.nct_id = '{nct_id}'""", limit=1)
    rows = result.get("rows") or []
    return rows[0] if rows else None


def snapshot_date() -> str | None:
    try:
        result = run_select("SELECT max(built_at) AS built_at FROM snapshot_meta", limit=1)
        return str(result["rows"][0]["built_at"]) if result.get("rows") else None
    except SnapshotMissing:
        return None
