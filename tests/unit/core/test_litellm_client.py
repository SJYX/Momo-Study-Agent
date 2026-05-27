"""tests/unit/core/test_litellm_client.py"""
import pytest
from unittest.mock import patch, MagicMock


def test_init_requires_api_key():
    from core.litellm_client import LiteLLMClient
    with pytest.raises(ValueError, match="API key"):
        LiteLLMClient(model="openai/mimo-v2-flash", api_key="")


def test_init_stores_params():
    from core.litellm_client import LiteLLMClient
    client = LiteLLMClient(
        model="openai/mimo-v2-flash",
        api_key="test-key",
        base_url="https://example.com/v1",
    )
    assert client.model == "openai/mimo-v2-flash"
    assert client.api_key == "test-key"
    assert client.base_url == "https://example.com/v1"


def test_generate_with_instruction_returns_text_and_usage():
    from core.litellm_client import LiteLLMClient

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"results": []}'
    mock_response.choices[0].finish_reason = "stop"
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 20
    mock_response.usage.total_tokens = 30

    client = LiteLLMClient(model="openai/test", api_key="key")

    mock_litellm = MagicMock()
    mock_litellm.completion.return_value = mock_response
    with patch("core.litellm_client._get_litellm", return_value=mock_litellm):
        text, metadata = client.generate_with_instruction("test prompt")

    assert text == '{"results": []}'
    assert metadata["prompt_tokens"] == 10
    assert metadata["completion_tokens"] == 20
    assert metadata["total_tokens"] == 30
    mock_litellm.completion.assert_called_once()


def test_generate_with_instruction_passes_system_instruction():
    from core.litellm_client import LiteLLMClient

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "ok"
    mock_response.choices[0].finish_reason = "stop"
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 5
    mock_response.usage.completion_tokens = 5
    mock_response.usage.total_tokens = 10

    client = LiteLLMClient(model="openai/test", api_key="key")

    mock_litellm = MagicMock()
    mock_litellm.completion.return_value = mock_response
    with patch("core.litellm_client._get_litellm", return_value=mock_litellm):
        client.generate_with_instruction("prompt", instruction="custom system")

    call_kwargs = mock_litellm.completion.call_args
    messages = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages")
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "custom system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "prompt"


def test_generate_with_instruction_retries_on_failure():
    from core.litellm_client import LiteLLMClient

    success_response = MagicMock()
    success_response.choices = [MagicMock()]
    success_response.choices[0].message.content = "success"
    success_response.choices[0].finish_reason = "stop"
    success_response.usage = MagicMock()
    success_response.usage.prompt_tokens = 5
    success_response.usage.completion_tokens = 5
    success_response.usage.total_tokens = 10

    client = LiteLLMClient(model="openai/test", api_key="key")

    mock_litellm = MagicMock()
    mock_litellm.completion.side_effect = [Exception("timeout"), success_response]
    with patch("core.litellm_client._get_litellm", return_value=mock_litellm):
        with patch("core.litellm_client.time.sleep"):
            text, metadata = client.generate_with_instruction("prompt")

    assert text == "success"


def test_generate_with_instruction_returns_empty_on_all_failures():
    from core.litellm_client import LiteLLMClient

    client = LiteLLMClient(model="openai/test", api_key="key")

    mock_litellm = MagicMock()
    mock_litellm.completion.side_effect = Exception("fail")
    with patch("core.litellm_client._get_litellm", return_value=mock_litellm):
        with patch("core.litellm_client.time.sleep"):
            text, metadata = client.generate_with_instruction("prompt")

    assert text == ""
    assert "error" in metadata
