"""query_trials_sql accepts one read-only SELECT and enforces a LIMIT."""

from ghost.db import check_select


def test_accepts_select():
    assert check_select("SELECT * FROM trials") is None
    assert check_select("WITH x AS (SELECT 1) SELECT * FROM x;") is None
    assert check_select("SELECT * FROM trials WHERE why_stopped ILIKE '%update%'") is None


def test_rejects_writes_and_tricks():
    for sql in ["DROP TABLE trials", "SELECT 1; DROP TABLE trials", "INSERT INTO trials VALUES (1)",
                "COPY trials TO 'x.csv'", "SELECT * FROM trials WHERE x = 'NA'", "ATTACH 'x.db'", "PRAGMA version", ""]:
        assert check_select(sql), sql
