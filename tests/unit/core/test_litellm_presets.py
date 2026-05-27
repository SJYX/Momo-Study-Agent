"""tests/unit/core/test_litellm_presets.py"""
import pytest
from core.litellm_presets import PROVIDERS, get_models_for_provider, get_default_base_url


def test_providers_has_ten_entries():
    assert len(PROVIDERS) == 10


def test_each_provider_has_required_fields():
    for p in PROVIDERS:
        assert "id" in p
        assert "name" in p
        assert "prefix" in p
        assert "models" in p
        assert "needs_base_url" in p
        assert len(p["models"]) >= 1


def test_get_models_for_provider_valid():
    models = get_models_for_provider("gemini")
    assert "gemini-2.0-flash" in models


def test_get_models_for_provider_unknown():
    models = get_models_for_provider("nonexistent")
    assert models == []


def test_get_default_base_url_mimo():
    url = get_default_base_url("mimo")
    assert url == "https://api.xiaomimimo.com/v1"


def test_get_default_base_url_gemini():
    url = get_default_base_url("gemini")
    assert url is None
