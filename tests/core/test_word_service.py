"""
tests/core/test_word_service.py: WordService 业务编排层单元测试。

测试覆盖：
1. normalize_cloud_items —— 脏数据过滤、WordItem 构造
2. enrich_with_states —— 状态查询、自动 backfill
3. partition_by_processability —— 基于 WordState 的分组（M5 重写后）
4. mark_completed —— 标记完成、队列满降级
5. update_word_memory_aid —— 单词笔记编辑
"""

from typing import Dict, List
from unittest import mock

import pytest

from core.word_service import WordService
from core.word_models import WordItem
from database.word_state import WordState


@pytest.fixture
def word_service():
    """创建 WordService 实例。"""
    with mock.patch("core.word_service.get_logger"):
        return WordService()


class TestNormalizeCloudItems:
    """Test normalize_cloud_items: dirty data filtering & WordItem construction."""

    def test_empty_input(self, word_service):
        """空输入返回空列表。"""
        result = word_service.normalize_cloud_items([])
        assert result == []

    def test_valid_items(self, word_service):
        """有效项转换为 WordItem。"""
        raw_items = [
            {
                "voc_id": "v1",
                "voc_spelling": "apple",
                "voc_meanings": "苹果",
                "review_count": 5,
                "short_term_familiarity": 3.5,
            },
            {
                "id": "v2",  # 兼容 id / voc_id
                "spelling": "banana",  # 兼容 spelling / voc_spelling
                "meanings": "香蕉",
            },
        ]

        result = word_service.normalize_cloud_items(raw_items)
        assert len(result) == 2
        assert result[0].voc_id == "v1"
        assert result[0].spelling == "apple"
        assert result[1].voc_id == "v2"
        assert result[1].spelling == "banana"

    def test_dirty_data_filtered(self, word_service):
        """缺 voc_id/spelling 的脏数据被过滤。"""
        raw_items = [
            {"voc_id": "v1", "voc_spelling": "apple"},  # 有效
            {"voc_id": "v2"},  # 缺 spelling
            {"voc_spelling": "cherry"},  # 缺 voc_id
            {},  # 全缺
        ]

        result = word_service.normalize_cloud_items(raw_items)
        assert len(result) == 1
        assert result[0].spelling == "apple"

    def test_mixed_valid_invalid(self, word_service):
        """有效和无效混合。"""
        raw_items = [
            {"voc_id": "v1", "voc_spelling": "apple"},
            {"voc_id": "v2", "voc_spelling": ""},  # 空 spelling
            {"voc_id": "v3", "voc_spelling": "cherry"},
        ]

        result = word_service.normalize_cloud_items(raw_items)
        assert len(result) == 2
        assert result[0].spelling == "apple"
        assert result[1].spelling == "cherry"


class TestEnrichWithStates:
    """Test enrich_with_states: state query & auto backfill."""

    def test_empty_input(self, word_service):
        """空输入返回空列表。"""
        result = word_service.enrich_with_states([])
        assert result == []

    def test_enrich_with_states_success(self, word_service):
        """成功查询并附加状态。"""
        items = [
            WordItem(voc_id="v1", spelling="apple"),
            WordItem(voc_id="v2", spelling="banana"),
        ]

        with mock.patch(
            "core.word_service.get_word_states_in_batch"
        ) as mock_states:
            mock_states.return_value = {
                "v1": WordState.NOT_STARTED.value,
                "v2": WordState.SYNCED.value,
            }

            result = word_service.enrich_with_states(items, auto_backfill=True)

            assert len(result) == 2
            assert result[0][0].voc_id == "v1"
            assert result[0][1] == WordState.NOT_STARTED
            assert result[1][0].voc_id == "v2"
            assert result[1][1] == WordState.SYNCED

    def test_enrich_with_backfill_flag(self, word_service):
        """backfill 标志传递正确。"""
        items = [WordItem(voc_id="v1", spelling="apple")]

        with mock.patch(
            "core.word_service.get_word_states_in_batch"
        ) as mock_states:
            mock_states.return_value = {"v1": WordState.LOCAL_READY.value}

            word_service.enrich_with_states(items, auto_backfill=False)

            # 验证 auto_backfill=False 被传递
            mock_states.assert_called_once()
            call_kwargs = mock_states.call_args[1]
            assert call_kwargs.get("auto_backfill") is False


class TestPartitionByProcessability:
    """Test partition_by_processability: WordState-based grouping (M5 重写后)。"""

    def test_empty_input(self, word_service):
        """空输入返回两个空列表。"""
        unprocessed, processed = word_service.partition_by_processability([])
        assert unprocessed == []
        assert processed == []

    def test_all_not_started(self, word_service):
        """全部词 NOT_STARTED → 全部分到 unprocessed。"""
        enriched = [
            (WordItem(voc_id="v1", spelling="apple"), WordState.NOT_STARTED),
            (WordItem(voc_id="v2", spelling="banana"), WordState.NOT_STARTED),
        ]
        unprocessed, processed = word_service.partition_by_processability(enriched)
        assert len(unprocessed) == 2
        assert len(processed) == 0
        assert {u.voc_id for u in unprocessed} == {"v1", "v2"}

    def test_all_processed_states_grouped_correctly(self, word_service):
        """LOCAL_READY / SYNCED / CONFLICT / FAILED 都视为 processed。"""
        enriched = [
            (WordItem(voc_id="v1", spelling="a"), WordState.LOCAL_READY),
            (WordItem(voc_id="v2", spelling="b"), WordState.SYNCED),
            (WordItem(voc_id="v3", spelling="c"), WordState.CONFLICT),
            (WordItem(voc_id="v4", spelling="d"), WordState.FAILED),
        ]
        unprocessed, processed = word_service.partition_by_processability(enriched)
        assert len(unprocessed) == 0
        assert len(processed) == 4
        assert {p.voc_id for p in processed} == {"v1", "v2", "v3", "v4"}

    def test_mixed(self, word_service):
        """混合状态：NOT_STARTED → unprocessed，其余 → processed。"""
        enriched = [
            (WordItem(voc_id="v1", spelling="a"), WordState.NOT_STARTED),
            (WordItem(voc_id="v2", spelling="b"), WordState.LOCAL_READY),
            (WordItem(voc_id="v3", spelling="c"), WordState.SYNCED),
        ]
        unprocessed, processed = word_service.partition_by_processability(enriched)
        assert [u.voc_id for u in unprocessed] == ["v1"]
        assert {p.voc_id for p in processed} == {"v2", "v3"}

    def test_dry_run_word_treated_as_processed(self, word_service):
        """回归 case：DRY_RUN 词（只在 processed_words，无 ai_word_notes）对应
        LOCAL_READY，应分到 processed。这是 M5 修复的核心
        （见 docs/dev/AI_REVIEW_20260514_TODAY_TASK_PIPELINE.md §8.3）。

        修复前：partition 会把这种词遗漏（既不在 unprocessed 也不在 processed）。
        修复后：基于 WordState 分组，LOCAL_READY → processed。
        """
        enriched = [
            (WordItem(voc_id="vDRY", spelling="dryword"), WordState.LOCAL_READY),
        ]
        unprocessed, processed = word_service.partition_by_processability(enriched)
        assert len(unprocessed) == 0
        assert len(processed) == 1
        assert processed[0].voc_id == "vDRY"

    def test_exception_fallback_is_conservative(self, word_service):
        """异常降级：保守地把全部当 processed，避免雪崩式重调 AI。"""
        enriched = [
            (WordItem(voc_id="v1", spelling="a"), WordState.NOT_STARTED),
            (WordItem(voc_id="v2", spelling="b"), WordState.NOT_STARTED),
        ]

        # 触发异常：让 WordItem 比较抛错（通过破坏 state 比较）
        # 这里用 mock 在循环里抛异常更简单
        bad_state = mock.MagicMock()
        bad_state.__eq__ = mock.MagicMock(side_effect=RuntimeError("boom"))
        bad_enriched = [(WordItem(voc_id="v1", spelling="a"), bad_state)]

        unprocessed, processed = word_service.partition_by_processability(bad_enriched)
        # 降级：unprocessed 空，全部分到 processed
        assert unprocessed == []
        assert len(processed) == 1


class TestMarkCompleted:
    """Test mark_completed: batch marking & queue full degradation."""

    def test_empty_input(self, word_service):
        """空输入返回 True。"""
        result = word_service.mark_completed([])
        assert result is True

    def test_mark_success(self, word_service):
        """标记成功。"""
        items = [
            WordItem(voc_id="v1", spelling="apple"),
            WordItem(voc_id="v2", spelling="banana"),
        ]

        with mock.patch("core.word_service.mark_processed_batch") as mock_mark:
            mock_mark.return_value = True

            result = word_service.mark_completed(items, batch_id="bid123")

            assert result is True
            mock_mark.assert_called_once()
            # 验证参数正确
            args = mock_mark.call_args[0][0]
            assert args == [("v1", "apple"), ("v2", "banana")]

    def test_queue_full(self, word_service):
        """队列满返回 False。"""
        items = [WordItem(voc_id="v1", spelling="apple")]

        with mock.patch("core.word_service.mark_processed_batch") as mock_mark:
            mock_mark.return_value = False

            result = word_service.mark_completed(items)

            assert result is False


class TestUpdateWordMemoryAid:
    """Test update_word_memory_aid: note editing."""

    def test_empty_voc_id(self, word_service):
        """空 voc_id 返回 False。"""
        result = word_service.update_word_memory_aid("", "new note")
        assert result is False

    def test_update_success(self, word_service):
        """更新成功。"""
        with mock.patch("core.word_service.update_memory_aid") as mock_update:
            mock_update.return_value = True

            result = word_service.update_word_memory_aid("v1", "new memory aid")

            assert result is True
            mock_update.assert_called_once()


class TestIntegration:
    """集成测试：完整工作流（mocked）。"""

    def test_normalize_valid_items(self, word_service):
        """end-to-end: 从 raw items 到 normalized。"""
        raw_items = [
            {"voc_id": "v1", "voc_spelling": "apple", "voc_meanings": "苹果"},
            {"voc_id": "v2", "voc_spelling": "banana"},
            {"voc_spelling": "cherry"},  # 脏数据
        ]

        # 验证 normalize 正确处理了脏数据
        normalized = word_service.normalize_cloud_items(raw_items)
        assert len(normalized) == 2
        assert all(item.voc_id and item.spelling for item in normalized)
        assert normalized[0].voc_id == "v1"
        assert normalized[1].voc_id == "v2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
