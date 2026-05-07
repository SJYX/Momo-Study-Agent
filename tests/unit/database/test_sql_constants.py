"""tests/unit/database/test_sql_constants.py: 校验 SQL 常量与参数组装函数的字段数一致。"""
from __future__ import annotations

from database.sql_constants import (
    AI_BATCH_INSERT_SQL,
    AI_WORD_ITERATION_INSERT_SQL,
    NOTE_UPSERT_SQL,
    PROCESSED_UPSERT_SQL,
    PROGRESS_INSERT_SQL,
    SYSTEM_CONFIG_UPSERT_SQL,
    UNSYNCED_NOTE_COLUMNS,
    UNSYNCED_NOTES_SELECT_SQL,
    COMMUNITY_NOTE_LOOKUP_SQL_TEMPLATE,
)


def test_note_upsert_sql_field_count():
    assert NOTE_UPSERT_SQL.count("?") == 23


def test_processed_upsert_sql_field_count():
    assert PROCESSED_UPSERT_SQL.count("?") == 3


def test_progress_insert_sql_field_count():
    assert PROGRESS_INSERT_SQL.count("?") == 5


def test_ai_batch_insert_sql_field_count():
    assert AI_BATCH_INSERT_SQL.count("?") == 12


def test_ai_word_iteration_insert_sql_field_count():
    assert AI_WORD_ITERATION_INSERT_SQL.count("?") == 12


def test_system_config_upsert_sql_field_count():
    assert SYSTEM_CONFIG_UPSERT_SQL.count("?") == 3


def test_unsynced_note_columns_match_select_select_list():
    """UNSYNCED_NOTE_COLUMNS 必须严格按 SELECT 列顺序排列。"""
    select_part = UNSYNCED_NOTES_SELECT_SQL.split("FROM")[0].replace("SELECT", "").strip()
    selected = [c.strip() for c in select_part.split(",")]
    assert selected == UNSYNCED_NOTE_COLUMNS


def test_community_lookup_template_uses_placeholders_marker():
    """模板必须包含 {placeholders}，由调用方按 IN 长度填充。"""
    assert "{placeholders}" in COMMUNITY_NOTE_LOOKUP_SQL_TEMPLATE
    assert "ai_word_notes" in COMMUNITY_NOTE_LOOKUP_SQL_TEMPLATE
    assert "ai_batches" in COMMUNITY_NOTE_LOOKUP_SQL_TEMPLATE
    assert "batch_ai_provider" in COMMUNITY_NOTE_LOOKUP_SQL_TEMPLATE
