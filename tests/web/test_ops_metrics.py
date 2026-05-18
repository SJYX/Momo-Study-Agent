"""
tests/web/test_ops_metrics.py — /api/ops/metrics 与 /api/ops/metrics/reset 端点测试。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core import metrics
from web.backend.routers.ops import router as ops_router


@pytest.fixture(autouse=True)
def fresh_metrics():
    """每个用例独立的 metrics collector，避免互相污染。"""
    metrics.reset_collector_for_test()
    yield
    metrics.reset_collector_for_test()


@pytest.fixture
def ops_client(app):
    """挂载 ops_router 的 TestClient。"""
    app.include_router(ops_router)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestOpsMetrics:
    def test_empty_metrics_returns_none_percentiles(self, ops_client):
        """无数据时 percentile 全为 None、count=0。"""
        resp = ops_client.get("/api/ops/metrics?profile=alice")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["profile"] == "alice"
        assert data["api"]["p50"] is None
        assert data["api"]["p95"] is None
        assert data["api"]["count"] == 0
        assert data["db_batch_write"]["count"] == 0
        assert data["sync_queue_depth"]["count"] == 0
        assert data["window_ttl_s"] == 300

    def test_metrics_reflect_recorded_values(self, ops_client):
        """record 后 endpoint 应能读到对应百分位。"""
        coll = metrics.get_metrics_collector()
        for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
            coll.record("alice", "api.duration_ms", v)
            coll.record("alice", "db.batch_write.duration_ms", v * 2)

        resp = ops_client.get("/api/ops/metrics?profile=alice")
        body = resp.json()["data"]
        assert body["api"]["count"] == 5
        assert body["api"]["p50"] == pytest.approx(30.0)
        assert body["db_batch_write"]["count"] == 5
        assert body["db_batch_write"]["p50"] == pytest.approx(60.0)

    def test_profile_isolation(self, ops_client):
        """alice 与 bob 各看各的指标。"""
        coll = metrics.get_metrics_collector()
        coll.record("alice", "api.duration_ms", 100.0)
        coll.record("bob", "api.duration_ms", 200.0)

        ra = ops_client.get("/api/ops/metrics?profile=alice")
        rb = ops_client.get("/api/ops/metrics?profile=bob")
        # endpoint 自身会被 middleware 计入指标——所以 count >=1。我们关心 p50 是哪个值。
        # 因为 conftest 的 app 是不带 middleware 的轻量版，这里 endpoint 调用不会污染指标。
        assert ra.json()["data"]["api"]["p50"] == 100.0
        assert rb.json()["data"]["api"]["p50"] == 200.0

    def test_missing_profile_falls_back_to_global(self, ops_client):
        """profile 省略时归到 _global，profile 字段返回 _global。"""
        coll = metrics.get_metrics_collector()
        coll.record("_global", "api.duration_ms", 42.0)

        resp = ops_client.get("/api/ops/metrics")
        body = resp.json()["data"]
        assert body["profile"] == "_global"
        assert body["api"]["p50"] == 42.0

    def test_reset_single_profile(self, ops_client):
        """reset 仅清空指定 profile。"""
        coll = metrics.get_metrics_collector()
        coll.record("alice", "api.duration_ms", 100.0)
        coll.record("bob", "api.duration_ms", 200.0)

        resp = ops_client.post("/api/ops/metrics/reset?profile=alice")
        assert resp.status_code == 200
        assert resp.json()["data"]["cleared"] is True
        assert resp.json()["data"]["profile"] == "alice"

        ra = ops_client.get("/api/ops/metrics?profile=alice")
        rb = ops_client.get("/api/ops/metrics?profile=bob")
        assert ra.json()["data"]["api"]["count"] == 0
        assert rb.json()["data"]["api"]["count"] == 1  # bob 未受影响

    def test_reset_all(self, ops_client):
        """profile 省略时 reset 清空全部 profile 的指标。"""
        coll = metrics.get_metrics_collector()
        coll.record("alice", "api.duration_ms", 100.0)
        coll.record("bob", "api.duration_ms", 200.0)

        resp = ops_client.post("/api/ops/metrics/reset")
        assert resp.status_code == 200
        assert resp.json()["data"]["profile"] is None

        ra = ops_client.get("/api/ops/metrics?profile=alice")
        rb = ops_client.get("/api/ops/metrics?profile=bob")
        assert ra.json()["data"]["api"]["count"] == 0
        assert rb.json()["data"]["api"]["count"] == 0
