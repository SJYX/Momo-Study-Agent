"""
tests/web/test_session.py -- GET /api/session test.
"""
from __future__ import annotations
import pytest


class TestGetSession:
    def test_returns_session_info(self, client, monkeypatch):
        monkeypatch.setattr("config.AI_PROVIDER", "gemini")
        monkeypatch.setattr("config.BATCH_SIZE", 10)
        monkeypatch.setattr("config.DRY_RUN", False)
        monkeypatch.setattr("config.DB_PATH", "/tmp/test.db")
        resp = client.get("/api/session")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["active_user"] == "testuser"
        assert data["ai_provider"] == "gemini"
        assert data["batch_size"] == 10
        assert data["dry_run"] is False

    def test_response_has_user_id(self, client, monkeypatch):
        monkeypatch.setattr("config.AI_PROVIDER", "mimo")
        monkeypatch.setattr("config.BATCH_SIZE", 5)
        monkeypatch.setattr("config.DRY_RUN", True)
        monkeypatch.setattr("config.DB_PATH", "/tmp/x.db")
        body = client.get("/api/session").json()
        assert body["user_id"] == "testuser"

    def test_session_dry_run_true(self, client, monkeypatch):
        monkeypatch.setattr("config.AI_PROVIDER", "gemini")
        monkeypatch.setattr("config.BATCH_SIZE", 1)
        monkeypatch.setattr("config.DRY_RUN", True)
        monkeypatch.setattr("config.DB_PATH", "/tmp/d.db")
        body = client.get("/api/session").json()
        assert body["data"]["dry_run"] is True
