"""tests/unit/settings/test_settings.py: pydantic-settings 模型行为。"""
from __future__ import annotations

import pytest

from core import settings as settings_mod


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每个用例清掉 Settings 关心的 env 与缓存。"""
    keys_to_clear = [
        "MOMO_TOKEN", "GEMINI_API_KEY", "MIMO_API_KEY", "AI_PROVIDER",
        "TURSO_DB_URL", "TURSO_AUTH_TOKEN", "TURSO_HUB_DB_URL", "TURSO_HUB_AUTH_TOKEN",
        "TURSO_MGMT_TOKEN", "TURSO_ORG_SLUG", "TURSO_GROUP",
        "ADMIN_PASSWORD_HASH", "ENCRYPTION_KEY", "FORCE_CLOUD_MODE",
        "AUTO_WARMUP_SYNC_ENABLED", "SYNC_STATUS_HEAVY_QUERY_ENABLED", "BACKGROUND_RETRY_ENABLED",
        "BATCH_SIZE", "GEMINI_MODEL", "MIMO_MODEL", "MIMO_API_BASE",
    ]
    for k in keys_to_clear:
        monkeypatch.delenv(k, raising=False)
    settings_mod._settings = None
    yield
    settings_mod._settings = None


def test_defaults_when_env_unset():
    s = settings_mod.Settings()
    assert s.MOMO_TOKEN is None
    assert s.GEMINI_API_KEY is None
    assert s.MIMO_API_BASE == "https://api.xiaomimimo.com/v1"
    assert s.AI_PROVIDER == "mimo"
    assert s.GEMINI_MODEL == "gemini-2.0-flash"
    assert s.BATCH_SIZE == 1
    assert s.FORCE_CLOUD_MODE is False
    assert s.AUTO_WARMUP_SYNC_ENABLED is True
    assert s.SYNC_STATUS_HEAVY_QUERY_ENABLED is True
    assert s.BACKGROUND_RETRY_ENABLED is True


def test_env_overrides_default(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("BATCH_SIZE", "5")
    monkeypatch.setenv("FORCE_CLOUD_MODE", "true")
    monkeypatch.setenv("AUTO_WARMUP_SYNC_ENABLED", "false")
    s = settings_mod.Settings()
    assert s.AI_PROVIDER == "gemini"
    assert s.BATCH_SIZE == 5
    assert s.FORCE_CLOUD_MODE is True
    assert s.AUTO_WARMUP_SYNC_ENABLED is False


def test_invalid_bool_raises_validation_error(monkeypatch):
    monkeypatch.setenv("FORCE_CLOUD_MODE", "garbage")
    with pytest.raises(Exception):
        settings_mod.Settings()


def test_get_settings_caches():
    first = settings_mod.get_settings()
    second = settings_mod.get_settings()
    assert first is second


def test_rebuild_settings_invalidates_cache_on_failure(monkeypatch):
    """rebuild 失败时 _settings 应被置为 None，避免误用旧实例。"""
    monkeypatch.setenv("FORCE_CLOUD_MODE", "true")
    s1 = settings_mod.rebuild_settings()
    assert s1.FORCE_CLOUD_MODE is True

    monkeypatch.setenv("FORCE_CLOUD_MODE", "garbage")
    with pytest.raises(Exception):
        settings_mod.rebuild_settings()
    assert settings_mod._settings is None


def test_extra_env_keys_ignored(monkeypatch):
    """SettingsConfigDict(extra='ignore') 让无关 env 不报错。"""
    monkeypatch.setenv("SOME_RANDOM_THING", "hello")
    s = settings_mod.Settings()  # 不应抛
    assert s.AI_PROVIDER == "mimo"


def test_known_flags_match_feature_flags_module():
    """Settings 中 Kill Switch 字段与 feature_flags.known_flags 必须一致。"""
    from core.feature_flags import known_flags
    flags = known_flags()
    s = settings_mod.Settings()
    for f in flags:
        assert hasattr(s, f), f"Settings 缺少 {f}"
