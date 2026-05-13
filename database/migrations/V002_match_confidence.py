"""
V002_match_confidence.py: 新增 ai_word_notes.match_confidence 列。

存储释义同步时的匹配置信度（0.0~1.0）：
- 精确匹配 = 1.0
- 近似匹配 = SequenceMatcher ratio（>= similarity_threshold）
- 无匹配 / 无远端释义 = NULL

便于下游区分"真正一致"和"近似匹配"，支持统计与人工复核。
"""
from __future__ import annotations

from typing import Any

_ADD_COLUMNS = [
    ("ai_word_notes", "match_confidence", "REAL"),
    ("ai_word_notes", "match_reason", "TEXT"),
]


def _column_exists(cur: Any, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    rows = cur.fetchall() or []
    for row in rows:
        name = row[1] if not isinstance(row, dict) else row.get("name")
        if str(name) == column:
            return True
    return False


def apply(cur: Any) -> None:
    for table, column, ddl in _ADD_COLUMNS:
        if _column_exists(cur, table, column):
            continue
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
