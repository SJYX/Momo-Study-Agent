"""
tests/web/test_health.py — GET /api/health 测试。
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.backend.schemas import HealthInfo, ok_response


def test_health_endpoint_returns_ok():
    """GET /api/health 应返回 ok=true, status=ok, version。"""
    app = FastAPI()

    @app.get("/api/health")
    async def health():
        return ok_response(HealthInfo().model_dump())

    with TestClient(app) as c:
        resp = c.get("/api/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["error"] is None
    assert body["data"]["status"] == "ok"
    assert body["data"]["version"] == "1.0.0"


def test_health_response_format():
    """验证响应结构包含所有必需字段。"""
    app = FastAPI()

    @app.get("/api/health")
    async def health():
        return ok_response(HealthInfo().model_dump())

    with TestClient(app) as c:
        body = c.get("/api/health").json()

    assert set(body.keys()) >= {"ok", "data", "error", "user_id"}
    assert isinstance(body["ok"], bool)
