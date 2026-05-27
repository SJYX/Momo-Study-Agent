"""tests/unit/web/test_user_context_ai_client.py

Verifies that the helper which builds a LiteLLMClient from a ProfileConfig
honours the unified AI_API_KEY / AI_MODEL / AI_BASE_URL fields and routes
the provider prefix correctly. This is the central piece of fixes #3 and
#4 in the LiteLLM-migration code review.
"""
import pytest

from web.backend.profile_config import ProfileConfig


def _make_cfg(**overrides) -> ProfileConfig:
    defaults = dict(
        profile_name="asher",
        env_path="/tmp/asher.env",
        momo_token="",
        ai_provider="mimo",
        gemini_api_key="",
        gemini_model="",
        mimo_api_key="",
        mimo_api_base="",
        mimo_model="",
        ai_api_key="",
        ai_model="",
        ai_base_url="",
        db_path="/tmp/asher.db",
        test_db_path="/tmp/test-asher.db",
        turso_db_url="",
        turso_auth_token="",
    )
    defaults.update(overrides)
    return ProfileConfig(**defaults)


def test_builds_client_from_unified_ai_fields():
    """When cfg has ai_api_key/ai_model/ai_base_url, the resulting client
    must use them — NOT the legacy gemini_/mimo_ branch fields."""
    from web.backend.user_context import _build_ai_client_from_snapshot
    cfg = _make_cfg(
        ai_provider="anthropic",
        ai_api_key="sk-ant-1",
        ai_model="claude-sonnet-4-20250514",
        ai_base_url="",
        # legacy fields populated but wrong on purpose — must be ignored
        mimo_api_key="WRONG-mimo",
        mimo_api_base="https://api.xiaomimimo.com/v1",
        mimo_model="mimo-v2-flash",
    )
    client = _build_ai_client_from_snapshot(cfg)
    assert client.api_key == "sk-ant-1"
    assert client.model == "claude/claude-sonnet-4-20250514"
    assert client.base_url is None


def test_builds_client_for_qwen_with_base_url():
    from web.backend.user_context import _build_ai_client_from_snapshot
    cfg = _make_cfg(
        ai_provider="qwen",
        ai_api_key="sk-q",
        ai_model="qwen-plus",
        ai_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    client = _build_ai_client_from_snapshot(cfg)
    assert client.api_key == "sk-q"
    assert client.model == "openai/qwen-plus"
    assert client.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_builds_client_for_gemini_no_base_url_leak():
    """Critical: even if mimo_api_base is populated (e.g. from a stale wizard
    write), a gemini-provider config must NOT inherit the Mimo endpoint."""
    from web.backend.user_context import _build_ai_client_from_snapshot
    cfg = _make_cfg(
        ai_provider="gemini",
        ai_api_key="AIza-test",
        ai_model="gemini-2.0-flash",
        ai_base_url="",
        # Hostile legacy state from a previous wizard run.
        mimo_api_base="https://api.xiaomimimo.com/v1",
    )
    client = _build_ai_client_from_snapshot(cfg)
    assert client.api_key == "AIza-test"
    assert client.model == "gemini/gemini-2.0-flash"
    assert client.base_url is None


def test_builds_client_preserves_fully_qualified_model():
    from web.backend.user_context import _build_ai_client_from_snapshot
    cfg = _make_cfg(
        ai_provider="openai",
        ai_api_key="sk-1",
        ai_model="openai/gpt-4o",
    )
    client = _build_ai_client_from_snapshot(cfg)
    # Already prefixed — must not double-prefix.
    assert client.model == "openai/gpt-4o"


def test_builds_client_raises_when_api_key_empty():
    from web.backend.user_context import _build_ai_client_from_snapshot
    cfg = _make_cfg(
        ai_provider="gemini",
        ai_api_key="",  # nothing usable
        ai_model="gemini-2.0-flash",
    )
    with pytest.raises(ValueError):
        _build_ai_client_from_snapshot(cfg)


def test_builds_client_for_all_ten_providers_uses_correct_prefix():
    """Smoke test: every provider in litellm_presets.PROVIDERS must build
    a usable client with the correct LiteLLM prefix."""
    from core.litellm_presets import PROVIDERS, get_provider_prefix
    from web.backend.user_context import _build_ai_client_from_snapshot
    for p in PROVIDERS:
        cfg = _make_cfg(
            ai_provider=p["id"],
            ai_api_key="sk-test",
            ai_model=p["models"][0],
            ai_base_url=p["default_base_url"] or "",
        )
        client = _build_ai_client_from_snapshot(cfg)
        expected_prefix = get_provider_prefix(p["id"])
        assert client.model.startswith(expected_prefix), (
            f"provider={p['id']} expected prefix {expected_prefix!r}, "
            f"got model={client.model!r}"
        )
