"""tests/unit/database/backends/test_pyturso_push_pull_split.py

Task 1: 拆分 pyturso push/pull 方法
验证 do_push_only / do_pull_only / do_sync_on 的行为和异常传播。
"""
from __future__ import annotations

import pytest
from unittest.mock import Mock, patch, call

from database.backends._pyturso import PytursoBackend


# ── Test do_push_only ──


def test_do_push_only_calls_push_and_checkpoint():
    """do_push_only 调用 conn.push() 和 conn.checkpoint()。"""
    backend = PytursoBackend()
    mock_conn = Mock()
    mock_conn.push = Mock()
    mock_conn.checkpoint = Mock()

    backend.do_push_only(mock_conn)

    mock_conn.push.assert_called_once()
    mock_conn.checkpoint.assert_called_once()


def test_do_push_only_propagates_push_exception():
    """do_push_only 在 push 失败时传播异常。"""
    backend = PytursoBackend()
    mock_conn = Mock()
    mock_conn.push = Mock(side_effect=RuntimeError("push failed"))
    mock_conn.checkpoint = Mock()

    with pytest.raises(RuntimeError, match="push failed"):
        backend.do_push_only(mock_conn)

    mock_conn.push.assert_called_once()
    mock_conn.checkpoint.assert_not_called()


def test_do_push_only_propagates_checkpoint_exception():
    """do_push_only 在 checkpoint 失败时传播异常。"""
    backend = PytursoBackend()
    mock_conn = Mock()
    mock_conn.push = Mock()
    mock_conn.checkpoint = Mock(side_effect=RuntimeError("checkpoint failed"))

    with pytest.raises(RuntimeError, match="checkpoint failed"):
        backend.do_push_only(mock_conn)

    mock_conn.push.assert_called_once()
    mock_conn.checkpoint.assert_called_once()


def test_do_push_only_no_op_on_non_pyturso_conn():
    """do_push_only 对非 pyturso 连接（无 push 方法）是 no-op。"""
    backend = PytursoBackend()
    mock_conn = Mock(spec=[])  # No push/checkpoint methods

    backend.do_push_only(mock_conn)  # Should not raise


# ── Test do_pull_only ──


def test_do_pull_only_calls_pull():
    """do_pull_only 调用 conn.pull()。"""
    backend = PytursoBackend()
    mock_conn = Mock()
    mock_conn.pull = Mock()

    backend.do_pull_only(mock_conn)

    mock_conn.pull.assert_called_once()


@patch("database.backends._pyturso._debug_log")
def test_do_pull_only_logs_and_swallows_exception(mock_debug_log):
    """do_pull_only 在 pull 失败时记录日志但不传播异常。"""
    backend = PytursoBackend()
    mock_conn = Mock()
    mock_conn.pull = Mock(side_effect=RuntimeError("pull failed"))

    backend.do_pull_only(mock_conn)  # Should not raise

    mock_conn.pull.assert_called_once()
    # Verify warning was logged
    assert any(
        call_args[0][0].startswith("[pyturso do_pull_only] pull 失败")
        for call_args in mock_debug_log.call_args_list
    )


def test_do_pull_only_no_op_on_non_pyturso_conn():
    """do_pull_only 对非 pyturso 连接（无 pull 方法）是 no-op。"""
    backend = PytursoBackend()
    mock_conn = Mock(spec=[])  # No pull method

    backend.do_pull_only(mock_conn)  # Should not raise


# ── Test do_sync_on ──


def test_do_sync_on_calls_push_pull_in_order():
    """do_sync_on 按顺序调用 do_push_only 和 do_pull_only。"""
    backend = PytursoBackend()
    mock_conn = Mock()
    mock_conn.push = Mock()
    mock_conn.checkpoint = Mock()
    mock_conn.pull = Mock()

    backend.do_sync_on(mock_conn)

    # Verify order: push → checkpoint → pull
    assert mock_conn.push.call_count == 1
    assert mock_conn.checkpoint.call_count == 1
    assert mock_conn.pull.call_count == 1

    # Verify call order
    call_order = []
    for call_item in mock_conn.method_calls:
        call_order.append(call_item[0])

    push_idx = call_order.index("push")
    checkpoint_idx = call_order.index("checkpoint")
    pull_idx = call_order.index("pull")

    assert push_idx < checkpoint_idx < pull_idx


def test_do_sync_on_propagates_push_exception():
    """do_sync_on 在 push 失败时传播异常，不调用 pull。"""
    backend = PytursoBackend()
    mock_conn = Mock()
    mock_conn.push = Mock(side_effect=RuntimeError("push failed"))
    mock_conn.checkpoint = Mock()
    mock_conn.pull = Mock()

    with pytest.raises(RuntimeError, match="push failed"):
        backend.do_sync_on(mock_conn)

    mock_conn.push.assert_called_once()
    mock_conn.checkpoint.assert_not_called()
    mock_conn.pull.assert_not_called()


@patch("database.backends._pyturso._debug_log")
def test_do_sync_on_continues_after_pull_failure(mock_debug_log):
    """do_sync_on 在 pull 失败时记录日志但不传播异常。"""
    backend = PytursoBackend()
    mock_conn = Mock()
    mock_conn.push = Mock()
    mock_conn.checkpoint = Mock()
    mock_conn.pull = Mock(side_effect=RuntimeError("pull failed"))

    backend.do_sync_on(mock_conn)  # Should not raise

    mock_conn.push.assert_called_once()
    mock_conn.checkpoint.assert_called_once()
    mock_conn.pull.assert_called_once()

    # Verify warning was logged
    assert any(
        call_args[0][0].startswith("[pyturso do_pull_only] pull 失败")
        for call_args in mock_debug_log.call_args_list
    )


def test_do_sync_on_no_op_on_non_pyturso_conn():
    """do_sync_on 对非 pyturso 连接（无 pull 方法）是 no-op。"""
    backend = PytursoBackend()
    mock_conn = Mock(spec=[])  # No push/pull/checkpoint methods

    backend.do_sync_on(mock_conn)  # Should not raise
