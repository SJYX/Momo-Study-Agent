"""
V005_is_customized.py: Add is_customized column to ai_word_notes.

User-edited memory_aid entries are marked is_customized=1 to prevent
cache overwrite. Default 0 (pure AI-generated, not user-edited).
"""
from __future__ import annotations
from typing import Any


def _column_exists(cur: Any, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    rows = cur.fetchall() or []
    for row in rows:
        name = row[1] if not isinstance(row, dict) else row.get("name")
        if str(name) == column:
            return True
    return False


def apply(cur: Any) -> None:
    if _column_exists(cur, "ai_word_notes", "is_customized"):
        return
    cur.execute("ALTER TABLE ai_word_notes ADD COLUMN is_customized INTEGER DEFAULT 0")
