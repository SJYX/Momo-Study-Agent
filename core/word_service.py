from __future__ import annotations
"""
core/word_service.py: 单词业务编排层（消费 word_repo 提供的统一数据访问）。

职责：
1. 标准化云端项目 → WordItem
2. 查询并附加 5 态状态信息
3. 按可处理性分组（基于 WordState：NOT_STARTED → 待处理，其余 → 已处理）
4. 批量标记处理完成
"""

from typing import Any, Dict, List, Optional, Tuple

from core.logger import get_logger
from core.word_models import WordItem
from database.word_repo import (
    get_word_states_in_batch,
    update_memory_aid,
)
from database.word_state import WordState
from database.progress_repo import mark_processed_batch


_logger = get_logger()


class WordService:
    """单词业务服务层。"""

    def __init__(self, logger=None):
        self.logger = logger or _logger

    # ========================================================================
    # 公开 API
    # ========================================================================

    def normalize_cloud_items(
        self, raw_items: List[Dict[str, Any]]
    ) -> Tuple[List[WordItem], int]:
        """归一化云端项目为 WordItem。

        过滤脏数据（缺 voc_id / spelling）。

        返回: (有效项列表, 丢弃数量)
        """
        if not raw_items:
            return [], 0

        normalized = []
        for raw in raw_items:
            item = WordItem.from_cloud_raw(raw)
            if item is not None:
                normalized.append(item)
            else:
                voc_id = raw.get("voc_id") or raw.get("id") or "<unknown>"
                spell = raw.get("voc_spelling") or raw.get("spelling") or "<missing>"
                self.logger.warning(
                    f"[normalize] 脏数据跳过: voc_id={voc_id}, spelling={spell}",
                    module="core.word_service",
                )

        return normalized, len(raw_items) - len(normalized)

    def enrich_with_states(
        self, items: List[WordItem], auto_backfill: bool = True
    ) -> List[Tuple[WordItem, WordState]]:
        """查询并附加 5 态状态。

        参数:
        - items: WordItem 列表
        - auto_backfill: 是否异步回填历史漏标（推荐 True）

        返回: [(item, state), ...] 列表

        实现: 单次 LEFT JOIN UNION，支持历史漏标自愈（O3）
        """
        if not items:
            return []

        voc_ids = [item.voc_id for item in items]

        try:
            states_dict = get_word_states_in_batch(
                voc_ids, auto_backfill=auto_backfill
            )
            result = []
            for item in items:
                state_str = states_dict.get(item.voc_id, WordState.NOT_STARTED.value)
                state = WordState(state_str)
                result.append((item, state))
            return result
        except Exception as e:
            self.logger.error(
                f"[enrich_with_states] 状态查询失败: {e}",
                module="core.word_service",
            )
            # 降级：全部标记为 NOT_STARTED（保守处理）
            return [(item, WordState.NOT_STARTED) for item in items]

    def partition_by_processability(
        self,
        enriched: List[Tuple[WordItem, WordState]],
    ) -> Tuple[List[WordItem], List[WordItem]]:
        """按可处理性分组：NOT_STARTED → 待处理，其余 4 态 → 已处理。

        参数:
        - enriched: enrich_with_states 的返回值 [(item, state), ...]
                    调用方必须先调 enrich 以避免重复查询。

        返回: (unprocessed, processed)

        覆盖语义：
        - NOT_STARTED  → 待处理（推送 AI）
        - LOCAL_READY  → 已处理（含 DRY_RUN 标记词 / 已生成笔记待同步词 / queued 词）
        - SYNCED       → 已处理（已远端确认）
        - CONFLICT     → 已处理（保留云端释义，等待用户在墨墨手动解冲突）
        - FAILED       → 已处理（不可重试，避免无限消耗 token）

        详见 docs/dev/AI_REVIEW_20260514_TODAY_TASK_PIPELINE.md §8。
        """
        if not enriched:
            return [], []

        try:
            unprocessed: List[WordItem] = []
            processed: List[WordItem] = []
            for item, state in enriched:
                if state == WordState.NOT_STARTED:
                    unprocessed.append(item)
                else:
                    processed.append(item)

            self.logger.info(
                f"[partition] 总 {len(enriched)} 词 → 待处理 {len(unprocessed)} 词，已处理 {len(processed)} 词",
                module="core.word_service",
            )
            return unprocessed, processed
        except Exception as e:
            self.logger.error(
                f"[partition_by_processability] 分组失败: {e}",
                module="core.word_service",
            )
            # 保守降级：全部当已处理，避免雪崩式重调 AI（详见审查报告 §8.6.2）
            return [], [item for item, _ in enriched]

    def mark_completed(
        self,
        items: List[WordItem],
        batch_id: Optional[str] = None,
        **extra_metadata,
    ) -> bool:
        """标记单词处理完成。

        参数:
        - items: 已处理完成的 WordItem 列表
        - batch_id: 可选的 AI 批次 ID（用于追踪）
        - **extra_metadata: 其他元数据（暂不使用）

        返回: 操作成功返回 True，队列满返回 False

        实现: 批量 INSERT INTO processed_words
        """
        if not items:
            return True

        try:
            # 组织参数：[(voc_id, spelling), ...]
            items_to_mark = [(item.voc_id, item.spelling) for item in items]

            ok = mark_processed_batch(items_to_mark)
            if ok:
                self.logger.info(
                    f"[mark_completed] 已标记 {len(items)} 词完成处理（batch_id={batch_id}）",
                    module="core.word_service",
                )
            else:
                self.logger.warning(
                    f"[mark_completed] 标记失败：写队列已满（{len(items)} 词）",
                    module="core.word_service",
                )
            return ok
        except Exception as e:
            self.logger.error(
                f"[mark_completed] 操作失败: {e}",
                module="core.word_service",
            )
            return False

    def update_word_memory_aid(
        self, voc_id: str, memory_aid: str, db_path: Optional[str] = None
    ) -> bool:
        """更新单个单词的 memory_aid（学习笔记）。

        便捷包装 word_repo.update_memory_aid。
        """
        if not voc_id:
            return False

        try:
            ok = update_memory_aid(voc_id, memory_aid, db_path=db_path)
            if ok:
                self.logger.debug(
                    f"[update_aid] voc_id={voc_id} 已更新",
                    module="core.word_service",
                )
            return ok
        except Exception as e:
            self.logger.error(
                f"[update_aid] voc_id={voc_id} 更新失败: {e}",
                module="core.word_service",
            )
            return False


__all__ = ["WordService"]
