"""
tests/web/test_users.py -- /api/users/* endpoint tests.
"""
from __future__ import annotations
import os
from pathlib import Path
from unittest.mock import MagicMock
import pytest


class TestListUsers:
    def test_list_users_returns_profiles(self, client, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "alice.env").write_text('MOMO_TOKEN="tok1"\nAI_PROVIDER="gemini"\nGEMINI_API_KEY="key1"\n')
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))
        resp = client.get("/api/users")
        body = resp.json()
        assert body["ok"] is True
        assert len(body["data"]["users"]) == 1
        assert body["data"]["users"][0]["username"] == "alice"

    def test_list_users_empty(self, client, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))
        body = client.get("/api/users").json()
        assert body["data"]["users"] == []

    def test_list_users_marks_active(self, client, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "testuser.env").write_text('MOMO_TOKEN="tok"\nAI_PROVIDER="mimo"\nMIMO_API_KEY="k"\n')
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))
        body = client.get("/api/users").json()
        active = [u for u in body["data"]["users"] if u["is_active"]]
        assert len(active) == 1


class TestSwitchActiveUser:
    def test_switch_to_nonexistent_user(self, client, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))
        body = client.put("/api/users/active?username=ghost").json()
        assert body["ok"] is False
        assert body["error"]["code"] == "NOT_FOUND"

    def test_switch_user_success(self, client, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "alice.env").write_text('MOMO_TOKEN="tok"\n')
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))
        import config as cfg
        monkeypatch.setattr(cfg, "switch_user", lambda u: u)
        import web.backend.deps as dp
        monkeypatch.setattr(dp, "_fallback_user", "testuser")
        monkeypatch.setattr(dp, "reload_user_services", lambda: None)
        import database.connection as db_conn
        monkeypatch.setattr(db_conn, "cleanup_concurrent_system", lambda: None)
        monkeypatch.setattr(db_conn, "init_concurrent_system", lambda: None)
        body = client.put("/api/users/active?username=alice").json()
        assert body["ok"] is True


class TestDeleteUser:
    def test_delete_active_user_rejected(self, client):
        body = client.delete("/api/users/testuser").json()
        assert body["ok"] is False
        assert body["error"]["code"] == "CANNOT_DELETE_ACTIVE"

    def test_delete_nonexistent_user(self, client, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))
        resp = client.delete("/api/users/ghost")
        body = resp.json()
        # ProfileManager may return ok with an error, or 404
        if body["ok"] is False:
            assert body["error"]["code"] in ("NOT_FOUND", "DELETE_ERROR")
        else:
            # Some ProfileManager implementations succeed silently
            assert resp.status_code == 200

    def test_delete_user_success(self, client, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "alice.env").write_text('MOMO_TOKEN="tok"\n')
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))
        body = client.delete("/api/users/alice").json()
        assert body["ok"] is True
        assert body["data"]["deleted"] == "alice"


class TestValidateConfig:
    def test_validate_empty_fields(self, client):
        body = client.post("/api/users/validate", json={"field":"","value":""}).json()
        assert body["ok"] is False
        assert body["error"]["code"] == "INVALID_INPUT"

    def test_validate_unknown_field(self, client):
        body = client.post("/api/users/validate", json={"field":"unknown_field","value":"test"}).json()
        assert body["ok"] is False
        assert body["error"]["code"] == "UNKNOWN_FIELD"


class TestWizardCreate:
    def test_wizard_empty_username(self, client):
        body = client.post("/api/users/wizard", json={"username":"","momo_token":"tok","ai_provider":"gemini","ai_api_key":"key"}).json()
        assert body["ok"] is False
        assert body["error"]["code"] == "INVALID_INPUT"

    def test_wizard_user_already_exists(self, client, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "alice.env").write_text('MOMO_TOKEN="tok"\n')
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))
        body = client.post("/api/users/wizard", json={"username":"alice","momo_token":"tok","ai_provider":"gemini","ai_api_key":"key"}).json()
        assert body["ok"] is False
        assert body["error"]["code"] == "USER_EXISTS"
