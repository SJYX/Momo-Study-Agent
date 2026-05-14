"""
V002_match_confidence.py: 新增 ai_word_notes.match_confidence / match_reason 列。

存储释义同步时的匹配置信度（0.0~1.0）：
- 精确匹配 = 1.0
- 近似匹配 = SequenceMatcher ratio（>= similarity_threshold）
- 无匹配 / 无远端释义 = NULL

便于下游区分"真正一致"和"近似匹配"，支持统计与人工复核。
"""
from __future__ import annotations

from .V001_initial import _column_exists

_ADD_COLUMNS = [
    ("ai_word_notes", "match_confidence", "REAL"),
    ("ai_word_notes", "match_reason", "TEXT"),
]


def apply(cur) -> None:
    for table, column, ddl in _ADD_COLUMNS:
        if _column_exists(cur, table, column):
            continue
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
