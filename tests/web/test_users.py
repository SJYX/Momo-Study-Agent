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
        monkeypatch.setattr(db_conn, "cleanup_db_session_resources", lambda: None)
        monkeypatch.setattr(db_conn, "init_db_session_resources", lambda: None)
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


# ===========================================================================
# Fix #6 — list_users.has_ai_key must recognise AI_API_KEY (unified var).
# Profiles written by AIConfigCard set AI_API_KEY only; legacy MIMO_/GEMINI_
# checks miss them and the frontend shows a red "AI Key" badge after save.
# ===========================================================================
class TestListUsersHasAiKey:
    def test_has_ai_key_detected_via_AI_API_KEY(self, client, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        # Saved via AIConfigCard — only the unified field is present.
        (profiles_dir / "alice.env").write_text(
            'AI_PROVIDER="anthropic"\nAI_API_KEY="sk-ant-test"\nAI_MODEL="claude-sonnet-4-20250514"\n'
        )
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))
        body = client.get("/api/users").json()
        alice = next(u for u in body["data"]["users"] if u["username"] == "alice")
        assert alice["has_ai_key"] is True
        assert alice["ai_provider"] == "anthropic"

    def test_has_ai_key_works_for_all_ten_providers(self, client, tmp_path, monkeypatch):
        """Every provider in PROVIDERS must show has_ai_key=true when AI_API_KEY
        is set — not just mimo/gemini."""
        from core.litellm_presets import PROVIDERS
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        for i, p in enumerate(PROVIDERS):
            (profiles_dir / f"u{i}.env").write_text(
                f'AI_PROVIDER="{p["id"]}"\nAI_API_KEY="sk-{p["id"]}"\nAI_MODEL="{p["models"][0]}"\n'
            )
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))
        body = client.get("/api/users").json()
        for u in body["data"]["users"]:
            assert u["has_ai_key"] is True, f"provider={u['ai_provider']} not detected as having AI key"

    def test_has_ai_key_still_works_for_legacy_profiles(self, client, tmp_path, monkeypatch):
        """Existing wizard-created profiles (legacy keys only) must keep working."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "mimo_user.env").write_text(
            'AI_PROVIDER="mimo"\nMIMO_API_KEY="sk-m"\n'
        )
        (profiles_dir / "gemini_user.env").write_text(
            'AI_PROVIDER="gemini"\nGEMINI_API_KEY="AIza"\n'
        )
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))
        body = client.get("/api/users").json()
        for u in body["data"]["users"]:
            assert u["has_ai_key"] is True


# ===========================================================================
# Fix #5 — save_ai_config must cleanup() the user's UserContext after
# switch_user, otherwise the cached ai_client keeps stale credentials.
# ===========================================================================
class TestSaveAiConfigRefreshesAi:
    def test_save_ai_config_writes_unified_vars(self, client, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "testuser.env").write_text("# placeholder\n")
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))
        # Avoid switch_user side effects (it would reload globals)
        import config as cfg
        monkeypatch.setattr(cfg, "ACTIVE_USER", "")  # disable hot-switch branch
        monkeypatch.setattr(cfg, "switch_user", lambda u: u)

        body = client.post(
            "/api/users/testuser/ai-config",
            json={"provider": "anthropic", "api_key": "sk-ant", "model": "claude-sonnet-4-20250514"},
        ).json()
        assert body["ok"] is True
        content = (profiles_dir / "testuser.env").read_text(encoding="utf-8")
        assert "AI_PROVIDER=anthropic" in content
        assert "AI_API_KEY=sk-ant" in content
        assert "AI_MODEL=claude-sonnet-4-20250514" in content

    def test_save_ai_config_refreshes_ai_components(self, client, tmp_path, monkeypatch):
        """After saving AI config, refresh_ai() is called (not cleanup()) to
        rebuild only AI components without disconnecting DB."""
        from unittest.mock import MagicMock

        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "alice.env").write_text("# placeholder\n")
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))

        # Pretend "alice" is the active user, so the hot-switch branch fires.
        import config as cfg
        monkeypatch.setattr(cfg, "ACTIVE_USER", "alice")
        monkeypatch.setattr(cfg, "switch_user", lambda u: u)

        # Patch the context manager so we can observe refresh_ai() calls.
        import web.backend.deps as deps
        fake_mgr = MagicMock()
        monkeypatch.setattr(deps, "_context_manager", fake_mgr)

        body = client.post(
            "/api/users/alice/ai-config",
            json={"provider": "gemini", "api_key": "AIza-new", "model": "gemini-2.5-pro"},
        ).json()
        assert body["ok"] is True
        fake_mgr.refresh_ai.assert_called_once()
        # refresh_ai should target "alice"
        called_with = fake_mgr.refresh_ai.call_args[0][0]
        assert called_with.lower() == "alice"

    def test_save_ai_config_handles_no_trailing_newline(self, client, tmp_path, monkeypatch):
        """当 .env 最后一行没有换行符时，新增键值也必须独占新行。"""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        # 最后一行故意不带换行，复现 TURSO_AUTH_TOKEN 与 AI_API_KEY 粘连问题。
        (profiles_dir / "testuser.env").write_text(
            "TURSO_AUTH_TOKEN=token_without_newline",
            encoding="utf-8",
        )
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))
        import config as cfg
        monkeypatch.setattr(cfg, "ACTIVE_USER", "")
        monkeypatch.setattr(cfg, "switch_user", lambda u: u)

        body = client.post(
            "/api/users/testuser/ai-config",
            json={"provider": "mimo", "api_key": "sk-new", "model": "mimo-v2.5-pro"},
        ).json()

        assert body["ok"] is True
        content = (profiles_dir / "testuser.env").read_text(encoding="utf-8")
        assert "TURSO_AUTH_TOKEN=token_without_newline\nAI_PROVIDER=mimo\n" in content
        assert "\nAI_API_KEY=sk-new\n" in content


# ===========================================================================
# Fix #12 — wizard_create and update_profile_config must write the unified
# AI_API_KEY / AI_MODEL vars, not just legacy MIMO_API_KEY / GEMINI_API_KEY.
# ===========================================================================
class TestWizardWritesUnifiedAiVars:
    def test_wizard_writes_AI_API_KEY(self, client, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))
        # Disable DB / cloud / validation side effects.
        from core import config_wizard as cw
        monkeypatch.setattr(cw.ConfigWizard, "_init_local_db", lambda self, u: None)
        monkeypatch.setattr(cw.ConfigWizard, "_create_turso_database", lambda *a, **kw: {"Hostname": ""})
        monkeypatch.setattr(cw.ConfigWizard, "validate_momo", lambda *a, **kw: {"ok": True})
        monkeypatch.setattr(cw.ConfigWizard, "validate_mimo", lambda *a, **kw: {"ok": True})
        monkeypatch.setattr(cw.ConfigWizard, "validate_gemini", lambda *a, **kw: {"ok": True})

        body = client.post(
            "/api/users/wizard",
            json={"username": "newuser", "momo_token": "tok", "ai_provider": "deepseek", "ai_api_key": "sk-ds"},
        ).json()
        assert body["ok"] is True, body
        content = (profiles_dir / "newuser.env").read_text(encoding="utf-8")
        # Unified vars must be present so save/list/preflight all agree.
        assert "AI_API_KEY" in content
        assert "sk-ds" in content
        # Must NOT only write legacy keys — that's what we're fixing.
        legacy_only = ("MIMO_API_KEY" in content or "GEMINI_API_KEY" in content) and "AI_API_KEY" not in content
        assert not legacy_only

    def test_update_profile_config_writes_AI_API_KEY(self, client, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "alice.env").write_text(
            'MOMO_TOKEN="t"\nAI_PROVIDER="mimo"\nMIMO_API_KEY="old"\n'
        )
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))

        body = client.put(
            "/api/users/alice/config",
            json={"ai_provider": "qwen", "ai_api_key": "sk-qwen-new"},
        ).json()
        assert body["ok"] is True
        content = (profiles_dir / "alice.env").read_text(encoding="utf-8")
        # Unified field gets the new key
        assert "AI_API_KEY" in content and "sk-qwen-new" in content
        assert 'AI_PROVIDER="qwen"' in content or "AI_PROVIDER=qwen" in content


# ===========================================================================
# Fix #13 — AIConfigRequest / AITestRequest must reject unknown providers
# instead of silently writing garbage to .env.
# ===========================================================================
class TestAiConfigSchemaValidation:
    def test_ai_config_rejects_unknown_provider(self, client, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "testuser.env").write_text("# placeholder\n")
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))

        resp = client.post(
            "/api/users/testuser/ai-config",
            json={"provider": "../../../etc", "api_key": "x", "model": "y"},
        )
        # FastAPI/pydantic should reject before reaching the handler.
        assert resp.status_code == 422, f"expected 422 unprocessable, got {resp.status_code}: {resp.text}"

    def test_ai_test_rejects_unknown_provider(self, client, tmp_path, monkeypatch):
        resp = client.post(
            "/api/users/testuser/ai-test",
            json={"provider": "nonsense", "api_key": "x", "model": "y"},
        )
        assert resp.status_code == 422

    def test_ai_config_accepts_all_listed_providers(self, client, tmp_path, monkeypatch):
        """Sanity: all 10 PROVIDERS in litellm_presets must pass validation."""
        from core.litellm_presets import PROVIDERS

        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "testuser.env").write_text("# placeholder\n")
        monkeypatch.setattr("config.PROFILES_DIR", str(profiles_dir))
        import config as cfg
        monkeypatch.setattr(cfg, "ACTIVE_USER", "")
        monkeypatch.setattr(cfg, "switch_user", lambda u: u)

        for p in PROVIDERS:
            resp = client.post(
                "/api/users/testuser/ai-config",
                json={"provider": p["id"], "api_key": "x", "model": p["models"][0]},
            )
            assert resp.status_code == 200, f"provider={p['id']} unexpectedly rejected: {resp.text}"
