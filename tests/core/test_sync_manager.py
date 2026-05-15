import pytest
from unittest.mock import MagicMock, patch
from core.sync_manager import SyncManager
import time
import queue

@pytest.fixture
def mock_deps():
    logger = MagicMock()
    momo_api = MagicMock()
    on_mark_processed = MagicMock()
    return logger, momo_api, on_mark_processed

def test_sync_manager_success_flow(mock_deps):
    """测试同步成功流程：入队 -> 调用 API -> 标记成功"""
    logger, momo_api, _ = mock_deps

    # 模拟 API 返回成功 (sync_status=1)
    momo_api.sync_interpretation.return_value = {"sync_status": 1}

    with patch("core.sync_manager.get_local_word_note", return_value=None), \
         patch("core.sync_manager.mark_processed_batch", return_value=True) as mock_processed_batch, \
         patch("core.sync_manager.update_sync_status_batch", return_value=True) as mock_update_status, \
         patch("core.sync_manager.mark_note_synced", return_value=True) as mock_mark:

        sm = SyncManager(logger, momo_api)

        # 入队同步任务
        sm.queue_maimemo_sync("v1", "apple", "n. 苹果", ["test"])

        # 等待队列被处理
        sm.sync_queue.join()
        sm.shutdown()

        # 验证 API 调用
        momo_api.sync_interpretation.assert_called_once()
        # 注意：由于现在采用批量刷盘逻辑，可能需要手动触发 flush 或等待
        sm.flush_pending_syncs("test_context")
        mock_processed_batch.assert_called_once()

def test_sync_manager_api_conflict_flow(mock_deps):
    """测试同步时 API 发现冲突 (状态 2)"""
    logger, momo_api, _ = mock_deps

    momo_api.sync_interpretation.return_value = {"sync_status": 2}

    with patch("core.sync_manager.get_local_word_note", return_value=None), \
         patch("core.sync_manager.mark_processed", return_value=True) as mock_processed, \
         patch("core.sync_manager.set_note_sync_status", return_value=True) as mock_set:

        sm = SyncManager(logger, momo_api)
        sm.queue_maimemo_sync("v1", "apple", "n. 苹果", ["test"])

        sm.sync_queue.join()
        sm.shutdown()

        # 验证状态设置 (忽略 db_path 参数)
        args, kwargs = mock_processed.call_args
        assert args == ("v1", "apple")
        mock_set.assert_called_with("v1", 2, match_confidence=None, match_reason=None)

def test_sync_manager_skip_already_synced(mock_deps):
    """测试如果本地已同步，则跳过 API 调用"""
    logger, momo_api, _ = mock_deps

    # 模拟本地状态为已同步 (sync_status=1)
    mock_note = {"voc_id": "v1", "sync_status": 1}

    with patch("core.sync_manager.get_local_word_note", return_value=mock_note):
        sm = SyncManager(logger, momo_api)
        sm.queue_maimemo_sync("v1", "apple", "n. 苹果", ["test"])

        sm.sync_queue.join()
        sm.shutdown()

        # 验证 API 未被调用
        momo_api.sync_interpretation.assert_not_called()

def test_sync_manager_shutdown_graceful(mock_deps):
    """测试停止管理时工作线程是否平滑退出"""
    logger, momo_api, _ = mock_deps

    sm = SyncManager(logger, momo_api)
    assert sm.sync_worker_thread.is_alive()

    sm.shutdown()
    assert not sm.sync_worker_thread.is_alive()
    assert sm._sync_worker_stopped is True

if __name__ == "__main__":
    pytest.main([__file__])
