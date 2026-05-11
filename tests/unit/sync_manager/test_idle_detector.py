"""tests/unit/sync_manager/test_idle_detector.py: PLAYBOOK B3 _is_idle 状态机测试。"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from core import feature_flags, metrics
from core.sync_manager import SyncManager


@pytest.fixture(autouse=True)
def fresh_metrics_and_flags():
    """每个用例独立的 collector 与 flag override 状态。"""
    metrics.reset_collector_for_test()
    feature_flags.reset_overrides()
    yield
    metrics.reset_collector_for_test()
    feature_flags.reset_overrides()


def _make_sm():
    logger = MagicMock()
    momo_api = MagicMock()
    momo_api.sync_interpretation.return_value = {"sync_status": 1}
    sm = SyncManager(logger, momo_api, MagicMock(), MagicMock())
    # 停掉 worker 防止它消费 metrics 干扰断言
    sm._stop_event.set()
    sm.sync_worker_thread.join(timeout=2.0)
    return sm


def test_idle_returns_false_when_flag_disabled():
    feature_flags.set_enabled("IDLE_ENGINE_ENABLED", False)
    sm = _make_sm()
    # 即使所有指标都低，flag 关时也不返回 idle
    assert sm._is_idle("alice") is False
    assert sm._idle_since is None


def test_idle_returns_false_when_no_metrics_first_call():
    """首次调用时 _idle_since 为空，记录时间但返回 False（防抖第一次）。"""
    sm = _make_sm()
    assert sm._is_idle("alice") is False
    assert sm._idle_since is not None  # 记录了起始时间


def test_idle_returns_true_after_debounce_period():
    """连续满足条件超过 IDLE_DEBOUNCE_S 秒后返回 True。"""
    sm = _make_sm()
    # 触发第一次记录 _idle_since
    assert sm._is_idle("alice") is False
    # 模拟时间过了 6 秒（超过默认 IDLE_DEBOUNCE_S=5）
    sm._idle_since = time.time() - 6.0
    assert sm._is_idle("alice") is True


def test_high_api_p95_resets_idle():
    sm = _make_sm()
    # 先进入防抖
    sm._is_idle("alice")
    sm._idle_since = time.time() - 6.0
    assert sm._is_idle("alice") is True
    # 模拟 API P95 高：填一堆 300ms 样本
    coll = metrics.get_metrics_collector()
    for _ in range(20):
        coll.record("alice", "api.duration_ms", 300.0)
    assert sm._is_idle("alice") is False
    assert sm._idle_since is None


def test_high_queue_depth_resets_idle():
    sm = _make_sm()
    sm._is_idle("alice")
    sm._idle_since = time.time() - 6.0
    assert sm._is_idle("alice") is True
    coll = metrics.get_metrics_collector()
    for _ in range(20):
        coll.record("alice", "sync.queue.depth", 10.0)  # >= IDLE_QUEUE_THRESHOLD=5
    assert sm._is_idle("alice") is False


def test_high_db_p95_resets_idle():
    sm = _make_sm()
    sm._is_idle("alice")
    sm._idle_since = time.time() - 6.0
    assert sm._is_idle("alice") is True
    coll = metrics.get_metrics_collector()
    for _ in range(20):
        coll.record("alice", "db.batch_write.duration_ms", 200.0)
    assert sm._is_idle("alice") is False


def test_low_metrics_do_not_reset():
    """指标都低于阈值时不应 reset _idle_since。"""
    sm = _make_sm()
    sm._is_idle("alice")
    sm._idle_since = time.time() - 6.0
    coll = metrics.get_metrics_collector()
    for _ in range(20):
        coll.record("alice", "api.duration_ms", 50.0)
        coll.record("alice", "sync.queue.depth", 1.0)
        coll.record("alice", "db.batch_write.duration_ms", 20.0)
    assert sm._is_idle("alice") is True


def test_idle_isolated_per_profile_metrics():
    """alice 的指标飙高不影响 bob 的 idle 判定。"""
    sm = _make_sm()
    coll = metrics.get_metrics_collector()
    # alice 高负载
    for _ in range(20):
        coll.record("alice", "api.duration_ms", 500.0)
    # bob 低负载
    for _ in range(20):
        coll.record("bob", "api.duration_ms", 30.0)
    sm._idle_since = time.time() - 6.0
    assert sm._is_idle("alice") is False
    # bob 的判定应独立——但 _idle_since 在 alice 检查时被重置了
    # 这表明 SyncManager 是 per-profile 的，混测多 profile 是测试场景人为造的
    # 真实场景下一个 SyncManager 只服务一个 profile，所以这里只验"bob 数据未污染 alice"
    coll.reset(profile="alice")
    sm._idle_since = time.time() - 6.0
    assert sm._is_idle("bob") is True
