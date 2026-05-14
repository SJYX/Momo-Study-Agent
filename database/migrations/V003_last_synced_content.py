"""
V003_last_synced_content.py: 新增 ai_word_notes.last_synced_content 列。

支持 3-Way Merge 冲突判定：
- 记录最近一次成功写入墨墨云端的清洗后内容。
- 只有本地最新内容 != last_synced_content，才认为本地有"新修改"；
- 如果云端内容 != last_synced_content，说明云端被用户或其他设备修改过。
- 如果两者同时发生且不一致，则报冲突（sync_status=2）。
"""
from __future__ import annotations

from .V001_initial import _column_exists

_ADD_COLUMNS = [
    ("ai_word_notes", "last_synced_content", "TEXT"),
]


def apply(cur) -> None:
    for table, column, ddl in _ADD_COLUMNS:
        if _column_exists(cur, table, column):
            continue
            
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        
    # 对历史已同步的词汇进行 backfill
    # 将 basic_meanings 的内容作为 baseline 填入
    cur.execute(
        "UPDATE ai_word_notes SET last_synced_content = basic_meanings "
        "WHERE sync_status = 1 AND last_synced_content IS NULL AND basic_meanings IS NOT NULL"
    )
