"""tests: update_memory_aid sets memory_aid + is_customized=1."""
import sqlite3
import pytest
from database.notes_repo import update_memory_aid


def _setup_db():
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE ai_word_notes ("
        "voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT, "
        "memory_aid TEXT, is_customized INTEGER DEFAULT 0, updated_at TEXT)"
    )
    cur.execute(
        "INSERT INTO ai_word_notes VALUES ('v1', 'hello', '你好', '原始记忆', 0, NULL)"
    )
    conn.commit()
    return conn


def test_update_memory_aid_sets_customized():
    conn = _setup_db()
    ok = update_memory_aid("v1", "用户自定义记忆", conn=conn)
    assert ok

    cur = conn.cursor()
    cur.execute("SELECT memory_aid, is_customized FROM ai_word_notes WHERE voc_id = 'v1'")
    row = cur.fetchone()
    assert row[0] == "用户自定义记忆"
    assert row[1] == 1


def test_update_memory_aid_nonexistent_voc_id():
    conn = _setup_db()
    # Should not raise, returns True (no rows affected but no error)
    ok = update_memory_aid("v999", "记忆", conn=conn)
    assert ok
