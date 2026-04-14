#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复现有数据库记录的 raw_full_text 字段
对于缺少 raw_full_text 的记录，从现有字段生成合理的文本
"""
import sys
sys.path.append('.')

from core.db_manager import _get_conn, DB_PATH, _debug_log
import sqlite3

def fix_legacy_raw_text(db_path=None):
    """修复遗留记录的 raw_full_text 字段"""
    path = db_path or DB_PATH
    conn = _get_conn(path)
    cur = conn.cursor()

    # 检查 ai_word_notes 表中哪些记录缺少 raw_full_text
    cur.execute("""
        SELECT voc_id, spelling, basic_meanings, memory_aid, raw_full_text
        FROM ai_word_notes
        WHERE raw_full_text IS NULL OR raw_full_text = '' OR raw_full_text LIKE '### %'
    """)

    legacy_records = cur.fetchall()
    _debug_log(f"发现 {len(legacy_records)} 条需要修复的遗留记录")

    fixed_count = 0
    for record in legacy_records:
        voc_id, spelling, basic_meanings, memory_aid, current_raw = record

        # 生成合理的 raw_full_text
        if not basic_meanings and not memory_aid:
            # 如果都没有内容，跳过
            continue

        # 组合现有内容为 markdown 格式
        sections = []
        sections.append(f"### {spelling}")

        if basic_meanings:
            sections.append(f"**基本含义：**\n{basic_meanings}")

        if memory_aid:
            sections.append(f"**记忆助记：**\n{memory_aid}")

        new_raw_text = "\n\n".join(sections)

        # 更新记录
        cur.execute("""
            UPDATE ai_word_notes
            SET raw_full_text = ?, updated_at = CURRENT_TIMESTAMP
            WHERE voc_id = ?
        """, (new_raw_text, voc_id))

        fixed_count += 1

        if fixed_count % 100 == 0:
            _debug_log(f"已修复 {fixed_count} 条记录...")

    conn.commit()
    conn.close()

    _debug_log(f"修复完成！共处理 {fixed_count} 条记录")
    return fixed_count

if __name__ == "__main__":
    fix_legacy_raw_text()