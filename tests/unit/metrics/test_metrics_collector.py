"""tests/unit/metrics/test_metrics_collector.py: MetricsCollector 多 profile 隔离与 snapshot 测试。"""
from __future__ import annotations

import pytest

from core.metrics import MetricsCollector


class TestMetricsCollector:
    def test_record_and_percentile(self):
        c = MetricsCollector()
        for v in [10, 20, 30, 40, 50]:
            c.record("alice", "api.duration_ms", float(v))
        p50 = c.percentile("alice", "api.duration_ms", 50)
        assert p50 == pytest.approx(30.0)
        p95 = c.percentile("alice", "api.duration_ms", 95)
        assert p95 == pytest.approx(48.0)

    def test_profile_isolation(self):
        c = MetricsCollector()
        c.record("alice", "api.duration_ms", 100.0)
        c.record("bob", "api.duration_ms", 200.0)
        # 各看各的
        assert c.percentile("alice", "api.duration_ms", 50) == 100.0
        assert c.percentile("bob", "api.duration_ms", 50) == 200.0
        # 不存在的 profile/metric 返回 None
        assert c.percentile("charlie", "api.duration_ms", 50) is None
        assert c.percentile("alice", "nonexistent", 50) is None

    def test_empty_profile_falls_back_to_global(self):
        c = MetricsCollector()
        c.record("", "api.duration_ms", 50.0)
        c.record(None, "api.duration_ms", 60.0)  # type: ignore[arg-type]
        # 两条都进 "_global" 桶
        assert c.count("_global", "api.duration_ms") == 2

    def test_snapshot_structure(self):
        c = MetricsCollector()
        c.record("alice", "api.duration_ms", 100.0)
        c.record("alice", "db.batch_write.duration_ms", 50.0)
        c.record("bob", "api.duration_ms", 200.0)

        snap = c.snapshot()
        assert "alice" in snap
        assert "bob" in snap
        assert "api.duration_ms" in snap["alice"]
        assert "db.batch_write.duration_ms" in snap["alice"]
        assert snap["alice"]["api.duration_ms"]["count"] == 1
        assert snap["alice"]["api.duration_ms"]["p50"] == 100.0

    def test_snapshot_filter_by_profile(self):
        c = MetricsCollector()
        c.record("alice", "api.duration_ms", 100.0)
        c.record("bob", "api.duration_ms", 200.0)

        snap = c.snapshot(profile="alice")
        assert "alice" in snap
        assert "bob" not in snap

    def test_reset_single_profile(self):
        c = MetricsCollector()
        c.record("alice", "api.duration_ms", 100.0)
        c.record("bob", "api.duration_ms", 200.0)

        c.reset(profile="alice")
        assert c.count("alice", "api.duration_ms") == 0
        # bob 不受影响
        assert c.count("bob", "api.duration_ms") == 1

    def test_reset_all(self):
        c = MetricsCollector()
        c.record("alice", "api.duration_ms", 100.0)
        c.record("bob", "api.duration_ms", 200.0)

        c.reset()
        assert c.count("alice", "api.duration_ms") == 0
        assert c.count("bob", "api.duration_ms") == 0

    def test_record_swallows_exceptions(self):
        """record 内部异常不应抛到调用方。"""
        c = MetricsCollector()
        # 用奇怪的 value 触发 float() 失败
        c.record("alice", "api.duration_ms", "not-a-number")  # type: ignore[arg-type]
        # 应静默忽略
        assert c.count("alice", "api.duration_ms") == 0
