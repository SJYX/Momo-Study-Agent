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
    on_conflict = MagicMock()
    return logger, momo_api, on_mark_processed, on_conflict

def test_sync_manager_success_flow(mock_deps):
    """测试同步成功流程：入队 -> 调用 API -> 标记成功"""
    logger, momo_api, on_mark_processed, on_conflict = mock_deps
    
    # 模拟 API 返回成功 (sync_status=1)
    momo_api.sync_interpretation.return_value = {"sync_status": 1}
    
    with patch("core.sync_manager.get_local_word_note", return_value=None), \
         patch("core.sync_manager.mark_processed", return_value=True) as mock_processed, \
         patch("core.sync_manager.mark_note_synced", return_value=True) as mock_mark:
        
        sm = SyncManager(logger, momo_api, on_mark_processed, on_conflict)
        
        # 入队同步任务
        sm.queue_maimemo_sync("v1", "apple", "n. 苹果", ["test"])
        
        # 等待队列被处理 (使用 join 会由于 worker 线程不退出而挂起，所以我们轮询或 shutdown)
        sm.sync_queue.join()
        sm.shutdown()
        
        # 验证 API 调用
        momo_api.sync_interpretation.assert_called_once()
        mock_processed.assert_called_with("v1", "apple")
        # 验证回调被触发
        on_mark_processed.assert_called_with("v1", "apple")
        mock_mark.assert_called_with("v1")

def test_sync_manager_deferred_conflict_flow(mock_deps):
    """测试已存在冲突的情况：DB 状态为 2"""
    logger, momo_api, on_mark_processed, on_conflict = mock_deps
    
    # 模拟本地状态已为冲突 (sync_status=2)
    mock_note = {"voc_id": "v1", "sync_status": 2}
    
    with patch("core.sync_manager.get_local_word_note", return_value=mock_note):
        sm = SyncManager(logger, momo_api, on_mark_processed, on_conflict)
        sm.queue_maimemo_sync("v1", "apple", "n. 苹果", ["test"])
        
        sm.sync_queue.join()
        sm.shutdown()
        
        # 结果：应触发 on_conflict 回调且跳过 API 同步
        on_conflict.assert_called_once()
        momo_api.sync_interpretation.assert_not_called()

def test_sync_manager_api_conflict_flow(mock_deps):
    """测试同步时 API 发现冲突 (状态 2)"""
    logger, momo_api, on_mark_processed, on_conflict = mock_deps
    
    momo_api.sync_interpretation.return_value = {"sync_status": 2}
    
    with patch("core.sync_manager.get_local_word_note", return_value=None), \
         patch("core.sync_manager.mark_processed", return_value=True) as mock_processed, \
         patch("core.sync_manager.set_note_sync_status", return_value=True) as mock_set:
        
        sm = SyncManager(logger, momo_api, on_mark_processed, on_conflict)
        sm.queue_maimemo_sync("v1", "apple", "n. 苹果", ["test"])
        
        sm.sync_queue.join()
        sm.shutdown()
        
        # 验证状态设置
        mock_processed.assert_called_with("v1", "apple")
        mock_set.assert_called_with("v1", 2)
        # 注意：根据当前代码实现，API 返回 2 时不会触发 on_conflict，只会记录日志
        on_conflict.assert_not_called()

def test_sync_manager_skip_already_synced(mock_deps):
    """测试如果本地已同步，则跳过 API 调用"""
    logger, momo_api, on_mark_processed, on_conflict = mock_deps
    
    # 模拟本地状态为已同步 (sync_status=1)
    mock_note = {"voc_id": "v1", "sync_status": 1}
    
    with patch("core.sync_manager.get_local_word_note", return_value=mock_note):
        sm = SyncManager(logger, momo_api, on_mark_processed, on_conflict)
        sm.queue_maimemo_sync("v1", "apple", "n. 苹果", ["test"])
        
        sm.sync_queue.join()
        sm.shutdown()
        
        # 验证 API 未被调用
        momo_api.sync_interpretation.assert_not_called()

def test_sync_manager_shutdown_graceful(mock_deps):
    """测试停止管理时工作线程是否平滑退出"""
    logger, momo_api, on_mark_processed, on_conflict = mock_deps
    
    sm = SyncManager(logger, momo_api, on_mark_processed, on_conflict)
    assert sm.sync_worker_thread.is_alive()
    
    sm.shutdown()
    assert not sm.sync_worker_thread.is_alive()
    assert sm._sync_worker_stopped is True

if __name__ == "__main__":
    pytest.main([__file__])
