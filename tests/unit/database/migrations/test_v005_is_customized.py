"""tests: V005_is_customized migration adds is_customized column."""
import sqlite3
import pytest
from database.migrations.V005_is_customized import apply


def _setup_db():
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE ai_word_notes (voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT)"
    )
    cur.execute(
        "INSERT INTO ai_word_notes VALUES ('v1', 'hello', '你好')"
    )
    conn.commit()
    return conn


def test_adds_is_customized_column():
    conn = _setup_db()
    cur = conn.cursor()
    apply(cur)
    conn.commit()

    cur.execute("PRAGMA table_info(ai_word_notes)")
    columns = [row[1] for row in cur.fetchall()]
    assert "is_customized" in columns


def test_default_is_zero():
    conn = _setup_db()
    cur = conn.cursor()
    apply(cur)
    conn.commit()

    cur.execute("SELECT is_customized FROM ai_word_notes WHERE voc_id = 'v1'")
    row = cur.fetchone()
    assert row[0] == 0


def test_is_idempotent():
    conn = _setup_db()
    cur = conn.cursor()
    apply(cur)
    conn.commit()
    # Second run should not raise
    apply(cur)
    conn.commit()

    cur.execute("SELECT is_customized FROM ai_word_notes WHERE voc_id = 'v1'")
    row = cur.fetchone()
    assert row[0] == 0
