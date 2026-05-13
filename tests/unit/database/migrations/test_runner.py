"""tests/unit/database/migrations/test_runner.py: PRAGMA user_version 框架行为。"""
from __future__ import annotations

import sqlite3

import pytest

from database.migrations import apply_migrations, current_version, target_version
from database.migrations.runner import MigrationError


def _fresh_db():
    """In-memory SQLite, 共享 cursor 风格的简易封装；这里直接用 raw connection."""
    return sqlite3.connect(":memory:")


def test_target_version_matches_v001():
    # V001_initial.py + V002_match_confidence.py 是当前已知迁移
    assert target_version() == 2


def test_empty_db_starts_at_v0():
    conn = _fresh_db()
    cur = conn.cursor()
    assert current_version(cur) == 0


def test_apply_migrations_to_empty_db_only_creates_user_version_marker():
    """全新空 DB 直接跑迁移：V001 的 ALTER 会在不存在的表上失败——
    但实际 init_db 流程是先 _create_tables 再迁移，所以这里我们模拟那个顺序。"""
    conn = _fresh_db()
    cur = conn.cursor()
    # 先建好骨架（与 _create_tables 中关键表对齐，最小集）
    cur.execute("CREATE TABLE processed_words (voc_id TEXT PRIMARY KEY, spelling TEXT)")
    cur.execute(
        "CREATE TABLE ai_word_notes ("
        "voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT, batch_id TEXT, "
        "it_level INTEGER DEFAULT 0, it_history TEXT, prompt_tokens INTEGER DEFAULT 0, "
        "completion_tokens INTEGER DEFAULT 0, total_tokens INTEGER DEFAULT 0, "
        "original_meanings TEXT, maimemo_context TEXT, content_origin TEXT, "
        "content_source_db TEXT, content_source_scope TEXT, raw_full_text TEXT, "
        "word_ratings TEXT, sync_status INTEGER DEFAULT 0, updated_at TIMESTAMP)"
    )
    conn.commit()

    start, end = apply_migrations(conn)
    assert start == 0
    assert end == 2
    assert current_version(cur) == 2


def test_idempotent_second_run_is_noop():
    conn = _fresh_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE processed_words (voc_id TEXT PRIMARY KEY, spelling TEXT, updated_at TIMESTAMP)")
    cur.execute("CREATE TABLE ai_word_notes (voc_id TEXT PRIMARY KEY, spelling TEXT, sync_status INTEGER DEFAULT 0, updated_at TIMESTAMP, batch_id TEXT, content_origin TEXT, content_source_scope TEXT, it_level INTEGER, it_history TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, original_meanings TEXT, maimemo_context TEXT, content_source_db TEXT, raw_full_text TEXT, word_ratings TEXT)")
    conn.commit()

    start1, end1 = apply_migrations(conn)
    start2, end2 = apply_migrations(conn)
    assert start1 == 0 and end1 == 2
    # 第二次跑：current >= target，立即返回
    assert start2 == 2 and end2 == 2


def test_legacy_db_without_some_columns_gets_columns_added():
    """模拟 v=0 的旧 DB：核心表存在，但新列还没加。V001 应当幂等地 ALTER 上去。"""
    conn = _fresh_db()
    cur = conn.cursor()
    # 老结构：只有最少列
    cur.execute("CREATE TABLE processed_words (voc_id TEXT PRIMARY KEY, spelling TEXT)")
    cur.execute("CREATE TABLE ai_word_notes (voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT)")
    conn.commit()

    apply_migrations(conn)

    # 验证新列被加上了
    cur.execute("PRAGMA table_info(ai_word_notes)")
    cols = {row[1] for row in cur.fetchall()}
    assert "sync_status" in cols
    assert "content_origin" in cols
    assert "updated_at" in cols
    assert "it_level" in cols
    assert "match_confidence" in cols
    assert "match_reason" in cols

    cur.execute("PRAGMA table_info(processed_words)")
    cols2 = {row[1] for row in cur.fetchall()}
    assert "updated_at" in cols2

    assert current_version(cur) == 2


def test_failure_in_migration_rolls_back_user_version(monkeypatch):
    """V001 + V002 之后再追加一个会爆的 V999，确保 V002 的 user_version=2 已落但 V999 不推进版本。"""
    import database.migrations.runner as runner_mod

    # 准备 DB：包含 V001 全部列 + V002 的列，模拟 V002 也已跑过的状态
    conn = _fresh_db()
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE processed_words (voc_id TEXT PRIMARY KEY, spelling TEXT, updated_at TIMESTAMP)"
    )
    cur.execute(
        "CREATE TABLE ai_word_notes ("
        "voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT, sync_status INTEGER, "
        "updated_at TIMESTAMP, batch_id TEXT, content_origin TEXT, content_source_scope TEXT, "
        "it_level INTEGER, it_history TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, "
        "total_tokens INTEGER, original_meanings TEXT, maimemo_context TEXT, content_source_db TEXT, "
        "raw_full_text TEXT, word_ratings TEXT, match_confidence REAL, match_reason TEXT)"
    )
    conn.commit()

    # monkeypatch discover：返回原本的 V001 + 一个虚构的 V999
    original_discover = runner_mod._discover_migrations

    def patched_discover():
        out = list(original_discover())
        out.append((999, "V999_bad"))
        return out

    def bad_apply(cur):
        raise RuntimeError("intentional")

    original_load = runner_mod._load_apply

    def patched_load(module_name):
        if module_name == "V999_bad":
            return bad_apply
        return original_load(module_name)

    monkeypatch.setattr(runner_mod, "_discover_migrations", patched_discover)
    monkeypatch.setattr(runner_mod, "_load_apply", patched_load)

    with pytest.raises(MigrationError) as ex:
        runner_mod.apply_migrations(conn)
    assert "V999" in str(ex.value)

    # V001 + V002 已成功提交，V999 在自己的事务里回滚 → user_version 应停在 2
    cur2 = conn.cursor()
    cur2.execute("PRAGMA user_version")
    assert cur2.fetchone()[0] == 2
