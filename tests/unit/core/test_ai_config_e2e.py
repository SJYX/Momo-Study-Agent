"""E2E verification: profile snapshot → LiteLLMClient → normalized kwargs."""
from unittest.mock import MagicMock, patch

from web.backend.profile_config import ProfileConfig
from web.backend.user_context import _build_ai_client_from_snapshot


def test_profile_snapshot_builds_client_without_double_prefix():
    snapshot = ProfileConfig(
        profile_name="demo",
        env_path="/tmp/demo.env",
        ai_provider="mimo",
        ai_protocol="anthropic",
        ai_api_key="secret",
        ai_model="mimo-v2-flash",
        ai_base_url="https://proxy.example.com/v1",
    )
    client = _build_ai_client_from_snapshot(snapshot)
    assert client.provider_id == "mimo"
    assert client.protocol == "anthropic"
    assert client.model == "mimo-v2-flash"


def test_factory_builds_provider_aware_client():
    with patch("core.factories.AI_API_KEY", "k"), \
         patch("core.factories.AI_PROVIDER", "mimo"), \
         patch("core.factories.AI_PROTOCOL", "anthropic"), \
         patch("core.factories.AI_MODEL", "mimo-v2-flash"), \
         patch("core.factories.AI_BASE_URL", ""):
        from core.factories import build_ai_client
        client = build_ai_client()
    assert client.provider_id == "mimo"
    assert client.protocol == "anthropic"
    assert client.model == "mimo-v2-flash"


def test_client_normalizes_kwargs_on_generate():
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content="ok"), finish_reason="stop")]
    response.usage = MagicMock(prompt_tokens=1, completion_tokens=2, total_tokens=3)
    response.id = "req-1"

    with patch("core.litellm_client._get_litellm") as get_llm:
        llm = MagicMock()
        llm.completion.return_value = response
        get_llm.return_value = llm

        snapshot = ProfileConfig(
            profile_name="demo",
            env_path="/tmp/demo.env",
            ai_provider="mimo",
            ai_protocol="anthropic",
            ai_api_key="secret",
            ai_model="mimo-v2-flash",
            ai_base_url=None,
        )
        client = _build_ai_client_from_snapshot(snapshot)
        text, meta = client.generate_with_instruction("hello", "reply with ok")

    assert text == "ok"
    kwargs = llm.completion.call_args.kwargs
    assert kwargs["model"] == "anthropic/mimo-v2-flash"
    assert kwargs["api_key"] == "secret"
    assert kwargs["api_base"] == "https://api.xiaomimimo.com/v1"
