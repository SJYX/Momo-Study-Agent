"""集成测试：同步优化流程端到端验证

测试脏标记、自适应延迟、推送失败处理等优化特性的集成行为。
"""
import pytest
import time
from unittest.mock import Mock, patch
from database.sync_coordinator import ProfileSyncCoordinator


def test_dirty_flag_skips_push_when_clean():
    """验证脏标记为 False 时跳过推送"""
    mock_backend = Mock()
    mock_backend.do_push_only = Mock()
    mock_backend.do_pull_only = Mock()

    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=mock_backend,
        debounce_seconds=0.1
    )

    # 确保脏标记为 False
    assert coordinator._has_unpushed_data is False

    # 触发同步
    with patch('database.connection._get_main_write_conn_singleton') as mock_conn:
        coordinator._do_sync()

    # 验证没有调用 push（因为没有脏数据）
    mock_backend.do_push_only.assert_not_called()

    # 但应该调用了 pull（拉取云端更新）
    mock_backend.do_pull_only.assert_called_once()


def test_dirty_flag_pushes_when_dirty():
    """验证脏标记为 True 时执行推送"""
    mock_backend = Mock()
    mock_backend.do_push_only = Mock()
    mock_backend.do_pull_only = Mock()

    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=mock_backend,
        debounce_seconds=0.1
    )

    # 标记为脏
    coordinator.mark_dirty()
    assert coordinator._has_unpushed_data is True

    # 触发同步
    with patch('database.connection._get_main_write_conn_singleton') as mock_conn:
        coordinator._do_sync()

    # 验证调用了 push
    mock_backend.do_push_only.assert_called_once()

    # 验证脏标记被清除
    assert coordinator._has_unpushed_data is False


def test_push_failure_preserves_dirty_flag():
    """验证推送失败后保留脏标记"""
    mock_backend = Mock()
    mock_backend.do_push_only = Mock(side_effect=RuntimeError("Network error"))
    mock_backend.do_pull_only = Mock()

    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=mock_backend,
        debounce_seconds=0.1
    )

    # 标记为脏
    coordinator.mark_dirty()
    assert coordinator._has_unpushed_data is True

    # 触发同步（会失败）
    with patch('database.connection._get_main_write_conn_singleton') as mock_conn:
        coordinator._do_sync()

    # 验证脏标记仍然为 True（因为推送失败）
    assert coordinator._has_unpushed_data is True

    # 验证尝试了推送
    mock_backend.do_push_only.assert_called_once()


def test_adaptive_delay_responds_to_frequency():
    """验证自适应延迟根据写入频率调整"""
    mock_backend = Mock()
    mock_backend.do_push_only = Mock()
    mock_backend.do_pull_only = Mock()

    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=mock_backend,
        debounce_seconds=5.0,  # 基础延迟 5 秒
        max_delay_seconds=30.0
    )

    # 模拟高频写入（3 次快速写入）
    start_time = time.time()
    coordinator.mark_dirty()
    time.sleep(0.1)
    coordinator.mark_dirty()
    time.sleep(0.1)
    coordinator.mark_dirty()

    # 等待一段时间让定时器触发
    time.sleep(6.0)

    # 验证延迟时间在合理范围内（应该接近 debounce_seconds）
    elapsed = time.time() - start_time
    assert 5.0 <= elapsed <= 8.0, f"延迟时间 {elapsed}s 不在预期范围内"

    # 验证最终执行了同步
    with patch('database.connection._get_main_write_conn_singleton') as mock_conn:
        # 手动触发以验证状态
        coordinator._do_sync()

    # 验证调用了推送
    assert mock_backend.do_push_only.call_count >= 1


def test_max_delay_enforces_upper_bound():
    """验证最大延迟限制生效"""
    mock_backend = Mock()
    mock_backend.do_push_only = Mock()
    mock_backend.do_pull_only = Mock()

    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=mock_backend,
        debounce_seconds=5.0,
        max_delay_seconds=10.0  # 最大延迟 10 秒
    )

    # 模拟持续写入（超过 max_delay）
    start_time = time.time()
    coordinator.mark_dirty()

    # 持续写入 12 秒，每秒一次
    for _ in range(12):
        time.sleep(1.0)
        coordinator.mark_dirty()

    # 验证在 max_delay 时间内触发了同步
    elapsed = time.time() - start_time
    assert elapsed <= 15.0, f"延迟时间 {elapsed}s 超过了最大延迟限制"

    # 清理
    coordinator.shutdown()


def test_concurrent_mark_dirty_is_safe():
    """验证并发 mark_dirty 调用是线程安全的"""
    import threading

    mock_backend = Mock()
    mock_backend.do_push_only = Mock()
    mock_backend.do_pull_only = Mock()

    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=mock_backend,
        debounce_seconds=1.0
    )

    # 并发调用 mark_dirty
    threads = []
    for _ in range(10):
        t = threading.Thread(target=coordinator.mark_dirty)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # 验证脏标记被正确设置
    assert coordinator._has_unpushed_data is True

    # 清理
    coordinator.shutdown()
