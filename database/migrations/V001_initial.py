"""
V001_initial.py: 收纳 Phase 6 之前由 ``CREATE TABLE IF NOT EXISTS`` + ``ALTER TABLE``
维护的所有"历史增量列"，让全新的库也能一次性达到与旧库同等结构。

注意：
- 现网存量 DB（``user_version=0`` 且核心表已存在）会被 runner 视为"实际 v1"
  直接打标签，**不会重跑此文件**。
- 这里只补 ALTER（add column）；首次 CREATE TABLE 仍由 ``database/schema.py::_create_tables``
  在 schema 初始化时跑（CREATE IF NOT EXISTS 是 v0 的合法做法）。
- ``ALTER TABLE ... ADD COLUMN`` 在 SQLite 中失败抛错就抛错，runner 会回滚整批。
  从 Phase 6 开始我们**不再静默吞 "duplicate column name"**——v0 → v1 的存量 DB
  根本不会进到这里，全新 DB 在 CREATE 后跑这里也不应当出现重复列。
"""
from __future__ import annotations

from typing import Any

# 与 _create_tables 现有列一致；按 (table, column, ddl_fragment) 顺序。
_ADD_COLUMNS = [
    ("ai_word_notes", "it_level", "INTEGER DEFAULT 0"),
    ("ai_word_notes", "it_history", "TEXT"),
    ("ai_word_notes", "prompt_tokens", "INTEGER DEFAULT 0"),
    ("ai_word_notes", "completion_tokens", "INTEGER DEFAULT 0"),
    ("ai_word_notes", "total_tokens", "INTEGER DEFAULT 0"),
    ("ai_word_notes", "batch_id", "TEXT"),
    ("ai_word_notes", "original_meanings", "TEXT"),
    ("ai_word_notes", "maimemo_context", "TEXT"),
    ("ai_word_notes", "content_origin", "TEXT"),
    ("ai_word_notes", "content_source_db", "TEXT"),
    ("ai_word_notes", "content_source_scope", "TEXT"),
    ("ai_word_notes", "raw_full_text", "TEXT"),
    ("ai_word_notes", "word_ratings", "TEXT"),
    ("ai_word_notes", "sync_status", "INTEGER DEFAULT 0"),
    ("ai_word_notes", "updated_at", "TIMESTAMP"),
    ("processed_words", "updated_at", "TIMESTAMP"),
]

_BACKFILL_STATEMENTS = [
    "UPDATE ai_word_notes SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL",
    "UPDATE processed_words SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL",
    (
        "UPDATE ai_word_notes SET content_origin = 'ai_generated', content_source_scope = 'ai_batch' "
        "WHERE content_origin IS NULL AND batch_id IS NOT NULL"
    ),
    (
        "UPDATE ai_word_notes SET content_origin = 'legacy_unknown', content_source_scope = 'legacy' "
        "WHERE content_origin IS NULL AND batch_id IS NULL"
    ),
]


def _column_exists(cur: Any, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    rows = cur.fetchall() or []
    for row in rows:
        # row 形态：(cid, name, type, notnull, dflt_value, pk)
        # libsql 以 sequence/dict 返回都可能；统一取第二位 name
        name = row[1] if not isinstance(row, dict) else row.get("name")
        if str(name) == column:
            return True
    return False


def apply(cur: Any) -> None:
    # ALTER：基于 PRAGMA table_info 提前判断列是否存在，存在则跳过；不存在再加。
    # 这样既避免对已有数据库重复 ALTER 抛错，也保证全新建库时所有列就位。
    for table, column, ddl in _ADD_COLUMNS:
        if _column_exists(cur, table, column):
            continue
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    # 数据回填：仅 V001 一次性跑，现存逻辑每次启动都跑是浪费。
    for sql in _BACKFILL_STATEMENTS:
        cur.execute(sql)
