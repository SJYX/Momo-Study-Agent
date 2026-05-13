from __future__ import annotations
"""
core/word_service.py: 单词业务编排层（消费 word_repo 提供的统一数据访问）。

职责：
1. 标准化云端项目 → WordItem
2. 查询并附加 5 态状态信息
3. 按可处理性分组（已处理 vs 待处理）
4. 批量标记处理完成

替代 study_workflow.py 的 9 个判重/自愈成员函数（Phase 7.4）。
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from core.logger import get_logger
from core.word_models import WordItem
from database.word_repo import (
    get_word_states_in_batch,
    filter_unprocessed,
    update_memory_aid,
)
from database.word_state import WordState
from database.progress_repo import mark_processed_batch, is_processed
from database.notes_repo import get_local_word_note, get_word_notes_in_batch


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
    ) -> List[WordItem]:
        """归一化云端项目为 WordItem。

        过滤脏数据（缺 voc_id / spelling）。

        返回: 有效项列表
        """
        if not raw_items:
            return []

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

        return normalized

    def enrich_with_states(
        self, items: List[WordItem], auto_backfill: bool = True
    ) -> List[Tuple[WordItem, WordState]]:
        """查询并附加 5 态状态。

        参数:
        - items: WordItem 列表
        - auto_backfill: 是否异步回填历史漏标（推荐 True）

        返回: [(item, state), ...] 列表

        实现: 单条 LEFT JOIN，支持历史漏标自愈（O3）
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
        self, items: List[WordItem]
    ) -> Tuple[List[WordItem], List[WordItem]]:
        """按可处理性分组：未处理 vs 已处理。

        需执行 3 套兜底判重：
        1. processed_words 表检查
        2. word_progress_history 历史记录检查
        3. ai_word_notes 本地笔记检查

        返回: (unprocessed, processed) 两个列表

        场景:
        - unprocessed: 词完全新增，可推送 AI
        - processed: 词已处理过，跳过 AI（可能待同步、冲突或已完成）
        """
        if not items:
            return [], []

        voc_ids_list = [item.voc_id for item in items]
        voc_ids_set = set(voc_ids_list)

        try:
            # 1. 快速通道：filter_unprocessed 直接返回 NOT_STARTED 集合
            unprocessed_ids = filter_unprocessed(voc_ids_list)

            # 2. 进度历史兜底（词已学习过，即使无笔记）
            remaining_ids = voc_ids_set - unprocessed_ids
            processed_from_progress = self._get_tracked_ids(remaining_ids)

            # 3. 本地笔记兜底（词有笔记但缺 processed 标记 → 自愈）
            processed_from_notes = self._get_ids_with_local_notes(
                remaining_ids - processed_from_progress
            )

            # 合并已处理集合
            final_processed_ids = processed_from_progress | processed_from_notes
            final_unprocessed_ids = unprocessed_ids

            # 分组
            unprocessed = [item for item in items if item.voc_id in final_unprocessed_ids]
            processed = [item for item in items if item.voc_id in final_processed_ids]

            self.logger.info(
                f"[partition] 总 {len(items)} 词 → 待处理 {len(unprocessed)} 词，已处理 {len(processed)} 词",
                module="core.word_service",
            )

            return unprocessed, processed
        except Exception as e:
            self.logger.error(
                f"[partition_by_processability] 分组失败: {e}",
                module="core.word_service",
            )
            # 降级：全部标记为待处理（保守处理）
            return items, []

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

    # ========================================================================
    # 内部辅助函数
    # ========================================================================

    def _get_tracked_ids(self, candidate_ids: Set[str]) -> Set[str]:
        """从 word_progress_history 查询已追踪的词（进度历史兜底）。

        这些词即使无 processed 标记也表示"已处理过"。
        """
        if not candidate_ids:
            return set()

        try:
            from database.progress_repo import get_progress_tracked_ids_in_batch

            tracked = get_progress_tracked_ids_in_batch(list(candidate_ids))
            return tracked
        except Exception as e:
            self.logger.warning(
                f"[_get_tracked_ids] 查询失败: {e}",
                module="core.word_service",
            )
            return set()

    def _get_ids_with_local_notes(
        self, candidate_ids: Set[str]
    ) -> Set[str]:
        """从 ai_word_notes 查询有笔记的词（笔记自愈兜底）。

        若词有笔记但缺 processed 标记，则：
        1. 识别该词已处理
        2. 异步入队 backfill processed_words
        """
        if not candidate_ids:
            return set()

        try:
            # 批量查询笔记
            notes_map = get_word_notes_in_batch(list(candidate_ids))
            if not notes_map:
                return set()

            # 识别"有笔记"的词
            ids_with_notes = set()
            to_backfill = []

            for voc_id in candidate_ids:
                note = notes_map.get(voc_id)
                if not note:
                    continue

                # 检查笔记内容非空
                has_content = bool(
                    str(note.get("basic_meanings") or "").strip()
                    or str(note.get("raw_full_text") or "").strip()
                    or str(note.get("memory_aid") or "").strip()
                )
                if has_content:
                    ids_with_notes.add(voc_id)
                    # 检查是否已标记 processed
                    if not is_processed(voc_id):
                        to_backfill.append(voc_id)

            # 异步入队 backfill（O3）
            if to_backfill:
                from database.word_repo import _enqueue_backfill_processed

                _enqueue_backfill_processed(to_backfill)
                self.logger.info(
                    f"[_get_ids_with_local_notes] 自愈回填 {len(to_backfill)} 词 processed 标记",
                    module="core.word_service",
                )

            return ids_with_notes
        except Exception as e:
            self.logger.warning(
                f"[_get_ids_with_local_notes] 查询失败: {e}",
                module="core.word_service",
            )
            return set()


__all__ = ["WordService"]
