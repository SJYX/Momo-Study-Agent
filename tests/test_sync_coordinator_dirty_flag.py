"""测试 ProfileSyncCoordinator 脏标记功能"""
import pytest
import time
from unittest.mock import Mock, patch
from database.sync_coordinator import ProfileSyncCoordinator


def test_mark_dirty_sets_flag():
    """验证 mark_dirty() 设置脏标记"""
    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=Mock(),
        debounce_seconds=1.0
    )

    assert coordinator._has_unpushed_data is False

    coordinator.mark_dirty()

    assert coordinator._has_unpushed_data is True


def test_push_success_clears_flag():
    """验证 push 成功后清除脏标记"""
    mock_backend = Mock()
    mock_backend.do_push_only = Mock()
    mock_backend.do_pull_only = Mock()

    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=mock_backend,
        debounce_seconds=0.1
    )

    # Direct manipulation for test isolation (avoids timer side effects)
    coordinator._has_unpushed_data = True

    with patch('database.connection._get_main_write_conn_singleton') as mock_conn:
        coordinator._do_sync()

    assert coordinator._has_unpushed_data is False


def test_push_failure_keeps_flag():
    """验证 push 失败后保留脏标记"""
    mock_backend = Mock()
    mock_backend.do_push_only = Mock(side_effect=RuntimeError("Network error"))

    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=mock_backend,
        debounce_seconds=0.1
    )

    coordinator._has_unpushed_data = True

    with patch('database.connection._get_main_write_conn_singleton'):
        coordinator._do_sync()

    # 失败后脏标记应保留
    assert coordinator._has_unpushed_data is True
