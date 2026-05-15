"""
V004_backfill_conflict_last_synced.py: 回填 sync_status=2 (冲突态) 词的 last_synced_content。

背景:
- V003 只回填了 sync_status=1 (已同步) 的词
- 246 个 sync_status=2 的词没有 last_synced_content，3-Way Merge 无法生效
- 这些冲突中大部分是旧算法（纯精确匹配）的误判，或旧版 AI 与新版 AI 的差异
- 用户选择放弃对少量手写释义的保护，统一回填当前 basic_meanings 作为 baseline
- 回填后，下次 retry_conflicts 时 3-Way Merge 会自动判断：
  - 云端 = 旧版 AI → 覆盖（成功）
  - 云端 = 用户手写 → 仍保留冲突（但不再有 3-Way Merge 自动处理）

幂等性: 只更新 last_synced_content IS NULL 的行，已有的不会被覆盖。
"""
from __future__ import annotations


def apply(cur) -> None:
    # 回填所有 sync_status=2 且 last_synced_content 为空的词
    # 使用 clean_for_maimemo 等价的 SQL（不剥 markdown，保留原始内容用于后续比对）
    cur.execute(
        "UPDATE ai_word_notes "
        "SET last_synced_content = basic_meanings "
        "WHERE sync_status = 2 AND last_synced_content IS NULL AND basic_meanings IS NOT NULL"
    )
