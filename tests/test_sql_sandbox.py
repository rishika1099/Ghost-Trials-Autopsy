"""The SQL tool's two walls: the text guard (one read-only SELECT) and the connection itself (read-only, no
file, network or environment access). A query that gets past the guard still can't reach anything outside."""

import pytest

from ghost import db
from ghost.db import check_select, run_select, trial_record

pytestmark = pytest.mark.skipif(not db.DB_PATH.exists(), reason="needs the snapshot")


@pytest.mark.parametrize("sql", [
    "dRoP TABLE trials",
    "SELECT 1 /* hide */ ; DELETE FROM trials",
    "SELECT 1;\nDROP TABLE trials;",
    "/* comment */ UPDATE trials SET title = 'x'",
    "-- note\nINSERT INTO trials SELECT * FROM trials",
    "WITH x AS (SELECT 1) DELETE FROM trials",
    "SELECT * FROM trials; SELECT 1",
    "CREATE TABLE t AS SELECT 1",
    "SET enable_external_access = true",
    "LOAD httpfs",
    "INSTALL httpfs",
    "EXPORT DATABASE 'out'",
    "CALL pragma_version()",
    "   ;  ",
    "-- only a comment",
    "EXPLAIN SELECT 1",
    "DESCRIBE trials",
])
def test_guard_rejects(sql):
    assert check_select(sql), sql


@pytest.mark.parametrize("sql", [
    "select nct_id from trials",
    "SELECT nct_id FROM trials -- trailing comment",
    "SELECT nct_id FROM trials /* block */",
    "SELECT nct_id FROM trials WHERE why_stopped ILIKE '%drop%'",
    "SELECT nct_id FROM trials WHERE title = 'It''s a delete trial'",
    "WITH s AS (SELECT * FROM trial_derived WHERE stopped) SELECT count(*) FROM s",
    "SELECT * FROM trials WHERE nct_id = 'NCT1' UNION ALL SELECT * FROM trials",
])
def test_guard_accepts_read_only_queries(sql):
    assert check_select(sql) is None, sql


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM read_text('/etc/hosts')",
    "SELECT * FROM glob('*')",
    "SELECT * FROM read_parquet('https://example.com/x.parquet')",
    "SELECT getenv('SEC_USER_AGENT') AS v",
])
def test_connection_blocks_files_network_and_env(sql):
    result = run_select(sql)
    assert "error" in result and "rows" not in result, result


def test_external_access_is_off_and_locked():
    rows = run_select("SELECT current_setting('enable_external_access') AS v")["rows"]
    assert rows == [{"v": False}]


def test_limit_is_enforced_even_when_the_query_asks_for_more():
    result = run_select("SELECT * FROM range(1000000) LIMIT 500000", limit=5)
    assert len(result["rows"]) == 5 and result["truncated"] is True


def test_small_result_is_not_marked_truncated():
    result = run_select("SELECT count(*) AS n FROM trials")
    assert result["truncated"] is False and result["rows"][0]["n"] > 0


def test_bad_sql_returns_an_error_not_an_exception():
    assert "error" in run_select("SELECT no_such_column FROM trials")
    assert "error" in run_select("SELECT * FROM no_such_table")


@pytest.mark.parametrize("nct_id", ["x' OR '1'='1", "NCT0000000", "NCT123456789", "nct00000000'", "", None, 12345])
def test_trial_record_rejects_anything_but_an_nct_id(nct_id):
    assert trial_record(nct_id) is None


def test_trial_record_finds_a_real_trial():
    nct = run_select("SELECT nct_id FROM trials LIMIT 1")["rows"][0]["nct_id"]
    row = trial_record(nct)
    assert row["nct_id"] == nct and "results_due_date" in row and "why_stopped_category" in row
