"""
tests/web/test_session.py -- GET /api/session test.

P0-T5 改造后 session 字段已固化为：
active_profile, available_profiles, server_time, host_binding。
旧字段（active_user/ai_provider/batch_size/dry_run）不再返回。
"""
from __future__ import annotations
import pytest


class TestGetSession:
    def test_returns_session_info(self, client):
        resp = client.get("/api/session")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["active_profile"] == "testuser"
        assert isinstance(data["available_profiles"], list)
        assert "server_time" in data
        assert data["host_binding"] == "127.0.0.1"

    def test_response_has_user_id(self, client):
        body = client.get("/api/session").json()
        assert body["user_id"] == "testuser"

    def test_session_host_binding_localhost(self, client):
        """第一阶段强约束：仅绑定 127.0.0.1（决策定版项 §2.3 #7）。"""
        body = client.get("/api/session").json()
        assert body["data"]["host_binding"] == "127.0.0.1"
