"""
tests/test_sync_manager_immediate_flush.py

验证 sync_status=1 成功路径立即写入数据库，不再使用写合并缓冲。
"""
import queue
import threading
import time
from unittest.mock import MagicMock, patch, call

import pytest

from core.sync_manager import SyncManager
from core.sync_priority import Priority


@pytest.fixture
def mock_logger():
    """Mock logger."""
    logger = MagicMock()
    return logger


@pytest.fixture
def mock_momo_api():
    """Mock Maimemo API."""
    api = MagicMock()
    return api


@pytest.fixture
def sync_manager(mock_logger, mock_momo_api):
    """Create SyncManager instance with mocked dependencies."""
    with patch("core.sync_manager.get_local_word_note") as mock_get_note:
        mock_get_note.return_value = {"sync_status": 0, "last_synced_content": None}
        manager = SyncManager(mock_logger, mock_momo_api, db_path=":memory:")
        yield manager
        manager.shutdown()


def test_sync_success_writes_immediately_no_buffer(sync_manager, mock_momo_api):
    """
    验证 sync_status=1 成功时立即调用 mark_note_synced 和 set_note_sync_status，
    不再积攒到 _pending_synced 和 _pending_status 缓冲区。
    """
    # Arrange: 模拟成功同步返回
    mock_momo_api.sync_interpretation.return_value = {
        "sync_status": 1,
        "match_confidence": 0.95,
        "match_reason": "exact_match",
        "cloud_interpretation": "test interpretation",
    }

    with patch("core.sync_manager.get_local_word_note") as mock_get_note, \
         patch("core.sync_manager.mark_note_synced") as mock_mark_synced, \
         patch("core.sync_manager.set_note_sync_status") as mock_set_status:

        mock_get_note.return_value = {"sync_status": 0, "last_synced_content": None}

        # Act: 入队并等待处理
        sync_manager.queue_maimemo_sync(
            voc_id="123",
            spell="test",
            interpretation="test interpretation",
            tags=["雅思"],
            priority=Priority.P1,
        )

        # 等待 worker 处理完成
        sync_manager.wait_for_sync_completion(timeout_s=5.0)

        # Assert: 验证立即调用了写入函数
        mock_mark_synced.assert_called_once_with("123", "test", db_path=":memory:")
        mock_set_status.assert_called_once_with(
            "123",
            1,
            db_path=":memory:",
            match_confidence=0.95,
            match_reason="exact_match",
            last_synced_content="test interpretation",
        )


def test_3way_merge_success_writes_immediately(sync_manager, mock_momo_api):
    """
    验证 3-Way Merge 成功路径（sync_status=2 → 1）也立即写入，不使用缓冲。
    """
    # Arrange: 模拟冲突检测 + 成功更新
    mock_momo_api.sync_interpretation.return_value = {
        "sync_status": 2,
        "cloud_id": "cloud_123",
        "cloud_interpretation": "old content",
    }
    mock_momo_api.update_interpretation.return_value = {"success": True}

    with patch("core.sync_manager.get_local_word_note") as mock_get_note, \
         patch("core.sync_manager.mark_note_synced") as mock_mark_synced, \
         patch("core.sync_manager.set_note_sync_status") as mock_set_status, \
         patch("core.sync_manager.clean_for_maimemo") as mock_clean:

        # 模拟 last_synced_content 与云端内容一致（触发 3-Way Merge）
        mock_get_note.return_value = {
            "sync_status": 0,
            "last_synced_content": "old content",
        }
        mock_clean.side_effect = lambda x: x  # 直通

        # Act
        sync_manager.queue_maimemo_sync(
            voc_id="456",
            spell="merge_test",
            interpretation="new content",
            tags=["雅思"],
            priority=Priority.P1,
        )

        sync_manager.wait_for_sync_completion(timeout_s=5.0)

        # Assert: 验证立即调用了写入函数
        mock_mark_synced.assert_called_once_with("456", "merge_test", db_path=":memory:")

        # 验证 set_note_sync_status 被调用，且 sync_status=1
        calls = mock_set_status.call_args_list
        assert len(calls) == 1
        assert calls[0][0][0] == "456"  # voc_id
        assert calls[0][0][1] == 1       # sync_status
        assert calls[0][1]["match_confidence"] == 1.0
        assert calls[0][1]["match_reason"] == "3-way-merged"


def test_conflict_path_unchanged(sync_manager, mock_momo_api):
    """
    验证冲突路径（sync_status=2 且非 3-Way Merge）行为不变：
    仍然立即写入，不使用缓冲（这是原有行为，确保未被破坏）。
    """
    # Arrange: 模拟冲突且无法 3-Way Merge
    mock_momo_api.sync_interpretation.return_value = {
        "sync_status": 2,
        "cloud_id": "cloud_789",
        "cloud_interpretation": "different content",
        "match_confidence": 0.5,
        "match_reason": "partial_match",
    }

    with patch("core.sync_manager.get_local_word_note") as mock_get_note, \
         patch("core.sync_manager.mark_processed") as mock_mark_processed, \
         patch("core.sync_manager.set_note_sync_status") as mock_set_status, \
         patch("core.sync_manager.clean_for_maimemo") as mock_clean:

        mock_get_note.return_value = {
            "sync_status": 0,
            "last_synced_content": "old content",
        }
        mock_clean.side_effect = lambda x: x

        # Act
        sync_manager.queue_maimemo_sync(
            voc_id="789",
            spell="conflict_test",
            interpretation="local content",
            tags=["雅思"],
            priority=Priority.P1,
        )

        sync_manager.wait_for_sync_completion(timeout_s=5.0)

        # Assert: 验证立即调用（原有行为）
        mock_mark_processed.assert_called_once_with("789", "conflict_test", db_path=":memory:")
        mock_set_status.assert_called_once_with(
            "789",
            2,
            db_path=":memory:",
            match_confidence=0.5,
            match_reason="partial_match",
        )


def test_failure_path_unchanged(sync_manager, mock_momo_api):
    """
    验证失败路径（sync_status=5）行为不变：立即写入，不使用缓冲。
    """
    # Arrange: 模拟非法 voc_id 失败
    mock_momo_api.sync_interpretation.return_value = {
        "sync_status": 0,
        "reason": "invalid_res_id",
    }

    with patch("core.sync_manager.get_local_word_note") as mock_get_note, \
         patch("core.sync_manager.set_note_sync_status") as mock_set_status:

        mock_get_note.return_value = {"sync_status": 0, "last_synced_content": None}

        # Act
        sync_manager.queue_maimemo_sync(
            voc_id="999",
            spell="invalid_test",
            interpretation="test",
            tags=["雅思"],
            priority=Priority.P1,
        )

        sync_manager.wait_for_sync_completion(timeout_s=5.0)

        # Assert: 验证立即写入 sync_status=5
        mock_set_status.assert_called_once_with(
            "999",
            5,
            db_path=":memory:",
            match_confidence=None,
            match_reason="invalid_res_id",
        )
