"""tests/unit/core/test_factories.py"""
import pytest
from unittest.mock import patch


def test_build_ai_client_returns_litellm_client():
    with patch("core.factories.AI_PROVIDER", "gemini"), \
         patch("core.factories.AI_API_KEY", "test-key"), \
         patch("core.factories.AI_MODEL", "gemini-2.0-flash"), \
         patch("core.factories.AI_BASE_URL", None):
        from core.factories import build_ai_client
        client = build_ai_client()
        from core.litellm_client import LiteLLMClient
        assert isinstance(client, LiteLLMClient)


def test_build_ai_client_raises_without_api_key():
    with patch("core.factories.AI_PROVIDER", "gemini"), \
         patch("core.factories.AI_API_KEY", ""), \
         patch("core.factories.AI_MODEL", "gemini-2.0-flash"), \
         patch("core.factories.AI_BASE_URL", None):
        from core.factories import build_ai_client
        with pytest.raises(ValueError):
            build_ai_client()
