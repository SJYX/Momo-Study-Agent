"""tests/unit/feature_flags/test_kill_switch.py: PLAYBOOK A4 Kill Switch 行为。"""
import os

import pytest

from core import feature_flags


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """每个用例前清掉 cache + override，并删掉相关 env，确保独立。"""
    feature_flags.reset_overrides()
    for name in feature_flags.known_flags():
        monkeypatch.delenv(name, raising=False)
    yield
    feature_flags.reset_overrides()


def test_default_true_when_env_unset():
    assert feature_flags.is_enabled("AUTO_WARMUP_SYNC_ENABLED") is True
    assert feature_flags.is_enabled("SYNC_STATUS_HEAVY_QUERY_ENABLED") is True
    assert feature_flags.is_enabled("BACKGROUND_RETRY_ENABLED") is True


def test_default_param_respected_when_env_unset():
    assert feature_flags.is_enabled("UNKNOWN_FLAG", default=False) is False
    feature_flags.reset_overrides()
    assert feature_flags.is_enabled("UNKNOWN_FLAG", default=True) is True


@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("true", True), ("True", True), ("YES", True), ("on", True),
    ("0", False), ("false", False), ("False", False), ("no", False), ("off", False),
])
def test_env_truthy_falsy_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("AUTO_WARMUP_SYNC_ENABLED", raw)
    feature_flags.reset_overrides()  # 清缓存让新 env 生效
    assert feature_flags.is_enabled("AUTO_WARMUP_SYNC_ENABLED") is expected


def test_unrecognized_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("AUTO_WARMUP_SYNC_ENABLED", "garbage")
    feature_flags.reset_overrides()
    assert feature_flags.is_enabled("AUTO_WARMUP_SYNC_ENABLED", default=True) is True
    feature_flags.reset_overrides()
    assert feature_flags.is_enabled("AUTO_WARMUP_SYNC_ENABLED", default=False) is False


def test_test_override_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("AUTO_WARMUP_SYNC_ENABLED", "true")
    feature_flags.set_enabled("AUTO_WARMUP_SYNC_ENABLED", False)
    assert feature_flags.is_enabled("AUTO_WARMUP_SYNC_ENABLED") is False


def test_cache_persists_across_calls(monkeypatch):
    monkeypatch.setenv("BACKGROUND_RETRY_ENABLED", "false")
    feature_flags.reset_overrides()
    first = feature_flags.is_enabled("BACKGROUND_RETRY_ENABLED")
    # 改 env 但不清缓存：应仍是旧值
    monkeypatch.setenv("BACKGROUND_RETRY_ENABLED", "true")
    second = feature_flags.is_enabled("BACKGROUND_RETRY_ENABLED")
    assert first is False
    assert second is False
    # 清缓存后才反映新 env
    feature_flags.reset_overrides()
    assert feature_flags.is_enabled("BACKGROUND_RETRY_ENABLED") is True


def test_known_flags_returns_expected_set():
    flags = feature_flags.known_flags()
    assert "AUTO_WARMUP_SYNC_ENABLED" in flags
    assert "SYNC_STATUS_HEAVY_QUERY_ENABLED" in flags
    assert "BACKGROUND_RETRY_ENABLED" in flags
