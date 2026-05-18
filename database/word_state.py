"""database/word_state.py: 单词 5 态状态机与推导规则。

5 个互斥状态：
    NOT_STARTED  — processed_words 无该 voc_id（判重 = 此态）
    LOCAL_READY  — processed + sync_status ∈ {0, NULL}（同步队列深度 = 此态计数）
    SYNCED       — sync_status = 1
    CONFLICT     — sync_status = 2（异常态，需用户处理）
    FAILED       — sync_status = 5（异常态，不可重试）

优先级（异常态压过正常态，便于前端高亮）：
    CONFLICT > FAILED > SYNCED > LOCAL_READY > NOT_STARTED

本模块只放纯定义和推导规则，无 DB 依赖。SQL 由 word_repo.py 使用。
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, Tuple


class WordState(str, Enum):
    """5 态状态机。继承 str 便于 JSON 序列化与 Web 端直接展示。"""

    NOT_STARTED = "not_started"
    LOCAL_READY = "local_ready"
    SYNCED = "synced"
    CONFLICT = "conflict"
    FAILED = "failed"


def derive_state(processed: bool, sync_status: Optional[int]) -> WordState:
    """根据 (processed_words 是否存在, ai_word_notes.sync_status) 推导状态。

    sync_status 语义（兼容 notes_repo.get_sync_status_in_batch 的映射）：
        None — ai_word_notes 中无该 voc_id（即没生成过笔记）
        0    — unsynced（本地已生成，未同步）
        1    — synced（远端已确认）
        2    — conflict（远端释义不一致）
        3    — queued（已废弃，代码内统一折叠为 0 处理）
        4    — syncing（已废弃，代码内统一折叠为 0 处理）
        5    — failed（不可重试失败）

    历史漏标兼容：当 sync_status ∈ {0,1} 但 processed=False 时，
    word_repo 内部会异步 backfill processed_words（O3）。
    """
    if sync_status == 2:
        return WordState.CONFLICT
    if sync_status == 5:
        return WordState.FAILED
    if sync_status == 1:
        return WordState.SYNCED
    if processed or sync_status == 0:
        return WordState.LOCAL_READY
    return WordState.NOT_STARTED


def state_to_where_clause(state: WordState) -> Tuple[str, Tuple]:
    """返回 (where_sql_fragment, params)，用于 word_repo 内部拼接到 JOIN 查询。

    约定 SQL 上下文：
        ... LEFT JOIN processed_words p ON p.voc_id = <候选表>.voc_id
            LEFT JOIN ai_word_notes  n ON n.voc_id = <候选表>.voc_id
            WHERE <fragment>

    与 derive_state 一一对应；优先级以 CONFLICT/FAILED 独立条件实现，
    SYNCED/LOCAL_READY/NOT_STARTED 用互斥 sync_status 范围保证不重叠。
    """
    if state == WordState.CONFLICT:
        return ("n.sync_status = ?", (2,))
    if state == WordState.FAILED:
        return ("n.sync_status = ?", (5,))
    if state == WordState.SYNCED:
        return ("n.sync_status = ?", (1,))
    if state == WordState.LOCAL_READY:
        return (
            "(p.voc_id IS NOT NULL OR n.sync_status = 0) "
            "AND (n.sync_status IS NULL OR n.sync_status NOT IN (1, 2, 5))",
            (),
        )
    # NOT_STARTED：processed_words 没记录 且 ai_word_notes 没记录
    return ("p.voc_id IS NULL AND n.sync_status IS NULL", ())


__all__ = ["WordState", "derive_state", "state_to_where_clause"]
