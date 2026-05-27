"""tests/unit/core/test_ai_legacy_fallbacks.py — fix #15 dedup helper.

Verifies the extracted _apply_ai_legacy_fallbacks helper used by both
config.py:module-load and config.py:switch_user. Without one helper the
two call sites drift.
"""
import pytest


def test_keeps_unified_values_when_set():
    from core.profile_loader import apply_ai_legacy_fallbacks
    api_key, model, base_url = apply_ai_legacy_fallbacks(
        provider="anthropic",
        ai_api_key="sk-ant",
        ai_model="claude-sonnet-4",
        ai_base_url="",
        gemini_api_key="WRONG-gemini",
        gemini_model="WRONG-gemini-model",
        mimo_api_key="WRONG-mimo",
        mimo_model="WRONG-mimo-model",
    )
    assert api_key == "sk-ant"
    assert model == "claude-sonnet-4"
    assert base_url == ""


def test_gemini_legacy_fallback():
    from core.profile_loader import apply_ai_legacy_fallbacks
    api_key, model, _ = apply_ai_legacy_fallbacks(
        provider="gemini",
        ai_api_key="",
        ai_model="",
        ai_base_url="",
        gemini_api_key="AIza-legacy",
        gemini_model="gemini-2.0-flash",
        mimo_api_key="should-not-leak",
        mimo_model="should-not-leak",
    )
    assert api_key == "AIza-legacy"
    assert model == "gemini-2.0-flash"


def test_mimo_legacy_fallback_with_default_base_url():
    from core.profile_loader import apply_ai_legacy_fallbacks
    api_key, model, base_url = apply_ai_legacy_fallbacks(
        provider="mimo",
        ai_api_key="",
        ai_model="",
        ai_base_url="",
        gemini_api_key="",
        gemini_model="",
        mimo_api_key="sk-mimo",
        mimo_model="mimo-v2-flash",
    )
    assert api_key == "sk-mimo"
    assert model == "mimo-v2-flash"
    assert base_url == "https://api.xiaomimimo.com/v1"


def test_non_mimo_keeps_empty_base_url():
    """deepseek/qwen/anthropic must NOT inherit Mimo's default base_url."""
    from core.profile_loader import apply_ai_legacy_fallbacks
    _, _, base_url = apply_ai_legacy_fallbacks(
        provider="deepseek",
        ai_api_key="sk-d",
        ai_model="deepseek-chat",
        ai_base_url="",
        gemini_api_key="",
        gemini_model="",
        mimo_api_key="",
        mimo_model="",
    )
    assert base_url == ""


def test_explicit_base_url_preserved():
    from core.profile_loader import apply_ai_legacy_fallbacks
    _, _, base_url = apply_ai_legacy_fallbacks(
        provider="mimo",
        ai_api_key="sk-x",
        ai_model="mimo-v2-flash",
        ai_base_url="https://my-proxy.example.com/v1",
        gemini_api_key="",
        gemini_model="",
        mimo_api_key="",
        mimo_model="",
    )
    assert base_url == "https://my-proxy.example.com/v1"
