"""tests/unit/core/test_litellm_client.py"""
import pytest
from unittest.mock import patch, MagicMock


def _make_response(content: str, prompt_tokens: int = 5, completion_tokens: int = 5,
                   total_tokens: int = 10, finish_reason: str = "stop"):
    """Build a MagicMock that mimics litellm.completion()'s response shape."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.choices[0].finish_reason = finish_reason
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    resp.usage.total_tokens = total_tokens
    return resp


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


# ---------------------------------------------------------------------------
# Fix #1: study_workflow.py:442 reads self.ai_client.model_name. Old
# MimoClient/GeminiClient exposed .model_name; LiteLLMClient must too.
# ---------------------------------------------------------------------------
def test_init_exposes_model_name_alias():
    from core.litellm_client import LiteLLMClient
    client = LiteLLMClient(model="gemini/gemini-2.0-flash", api_key="k")
    # Both attribute names should be valid — .model is the litellm.completion()
    # kwarg, .model_name is the legacy attribute callers read.
    assert client.model == "gemini/gemini-2.0-flash"
    assert client.model_name == "gemini/gemini-2.0-flash"


# ---------------------------------------------------------------------------
# Fix #9: old MimoClient passed temperature=0.7 and max_completion_tokens=64000
# so batches near BATCH_SIZE didn't truncate. LiteLLMClient must forward
# reasonable defaults (overridable via AI_TEMPERATURE / AI_MAX_TOKENS env vars).
# ---------------------------------------------------------------------------
def test_generate_with_instruction_passes_temperature_and_max_tokens():
    from core.litellm_client import LiteLLMClient
    client = LiteLLMClient(model="openai/test", api_key="key")
    mock_litellm = MagicMock()
    mock_litellm.completion.return_value = _make_response("ok")
    with patch("core.litellm_client._get_litellm", return_value=mock_litellm):
        client.generate_with_instruction("prompt")
    kwargs = mock_litellm.completion.call_args.kwargs
    assert "temperature" in kwargs, "old MimoClient set temperature=0.7; new client dropped it"
    assert kwargs["temperature"] == 0.7
    assert "max_tokens" in kwargs, "old MimoClient set max_completion_tokens=64000; new client dropped it"
    assert kwargs["max_tokens"] >= 4096


def test_generate_with_instruction_temperature_overridable_via_env():
    from core.litellm_client import LiteLLMClient
    mock_litellm = MagicMock()
    mock_litellm.completion.return_value = _make_response("ok")
    with patch.dict("os.environ", {"AI_TEMPERATURE": "0.2", "AI_MAX_TOKENS": "8192"}):
        client = LiteLLMClient(model="openai/test", api_key="key")
        with patch("core.litellm_client._get_litellm", return_value=mock_litellm):
            client.generate_with_instruction("prompt")
    kwargs = mock_litellm.completion.call_args.kwargs
    assert kwargs["temperature"] == 0.2
    assert kwargs["max_tokens"] == 8192


# ---------------------------------------------------------------------------
# Fix #10: generate_mnemonics needs to survive Gemini-style "prose + array + prose"
# responses. The old GeminiClient used a bracket-counting fallback
# (_extract_json_array). Without it, json_repair sometimes returns the wrong
# fragment and the batch is silently dropped.
# ---------------------------------------------------------------------------
def test_generate_mnemonics_parses_wrapped_results():
    from core.litellm_client import LiteLLMClient
    client = LiteLLMClient(model="openai/test", api_key="key")
    mock_litellm = MagicMock()
    payload = '{"results": [{"spelling": "apple"}, {"spelling": "banana"}]}'
    mock_litellm.completion.return_value = _make_response(payload, total_tokens=20)
    with patch("core.litellm_client._get_litellm", return_value=mock_litellm):
        results, metadata = client.generate_mnemonics(["apple", "banana"])
    assert len(results) == 2
    assert results[0]["spelling"] == "apple"
    assert results[1]["spelling"] == "banana"
    # token attribution: 20 total / 2 items = 10 each
    assert results[0]["total_tokens"] == 10


def test_generate_mnemonics_parses_bare_array_with_trailing_prose():
    """Gemini sometimes returns `[...] 这里的苹果很好吃 ]道路]` — old
    GeminiClient handled this via _extract_json_array bracket counting."""
    from core.litellm_client import LiteLLMClient
    client = LiteLLMClient(model="gemini/gemini-2.0-flash", api_key="key")
    mock_litellm = MagicMock()
    payload = '[{"spelling": "apple"}] 这里的苹果很好吃 ]道路]'
    mock_litellm.completion.return_value = _make_response(payload)
    with patch("core.litellm_client._get_litellm", return_value=mock_litellm):
        results, metadata = client.generate_mnemonics(["apple"])
    assert len(results) == 1, f"expected 1 result, got {results} (parser failed to strip trailing prose)"
    assert results[0]["spelling"] == "apple"


def test_generate_mnemonics_skips_non_dict_items():
    from core.litellm_client import LiteLLMClient
    client = LiteLLMClient(model="openai/test", api_key="key")
    mock_litellm = MagicMock()
    payload = '{"results": [{"spelling": "ok"}, "stray-string", 42, {"spelling": "ok2"}]}'
    mock_litellm.completion.return_value = _make_response(payload)
    with patch("core.litellm_client._get_litellm", return_value=mock_litellm):
        results, _ = client.generate_mnemonics(["a", "b"])
    assert len(results) == 2
    assert {r["spelling"] for r in results} == {"ok", "ok2"}


def test_generate_mnemonics_parse_failure_returns_empty():
    from core.litellm_client import LiteLLMClient
    client = LiteLLMClient(model="openai/test", api_key="key")
    mock_litellm = MagicMock()
    # Completely unparseable garbage (no JSON anywhere)
    mock_litellm.completion.return_value = _make_response("not json at all")
    with patch("core.litellm_client._get_litellm", return_value=mock_litellm):
        results, metadata = client.generate_mnemonics(["a"])
    # json_repair is permissive, but no [ or { means empty results.
    assert results == []


# ---------------------------------------------------------------------------
# Fix #14: close() should make a best-effort attempt to release litellm's
# internal HTTP clients. Old MimoClient.close() closed requests.Session;
# old GeminiClient.close() closed the genai client.
# ---------------------------------------------------------------------------
def test_close_is_safe_to_call_repeatedly():
    from core.litellm_client import LiteLLMClient
    client = LiteLLMClient(model="openai/test", api_key="key")
    # Calling close() must not raise even if litellm wasn't loaded.
    client.close()
    client.close()


# ---------------------------------------------------------------------------
# Fix #10 unit: the _extract_json_array helper itself.
# ---------------------------------------------------------------------------
def test_extract_json_array_recovers_from_trailing_garbage():
    from core.litellm_client import _extract_json_array
    text = '[{"spelling": "apple"}] 这里的苹果很好吃 ]道路]'
    assert _extract_json_array(text) == '[{"spelling": "apple"}]'


def test_extract_json_array_handles_nested():
    from core.litellm_client import _extract_json_array
    text = '[{"a": [1, 2]}, {"b": 3}] trailing'
    assert _extract_json_array(text) == '[{"a": [1, 2]}, {"b": 3}]'


def test_extract_json_array_no_array_returns_input():
    from core.litellm_client import _extract_json_array
    assert _extract_json_array("just prose, no brackets") == "just prose, no brackets"


def test_client_passes_exact_completion_kwargs():
    from unittest.mock import MagicMock, patch
    from core.litellm_client import LiteLLMClient

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "ok"
    response.choices[0].finish_reason = "stop"
    response.usage = MagicMock()
    response.usage.prompt_tokens = 1
    response.usage.completion_tokens = 2
    response.usage.total_tokens = 3
    response.id = "req-1"

    with patch("core.litellm_client._get_litellm") as get_llm:
        llm = MagicMock()
        llm.completion.return_value = response
        get_llm.return_value = llm

        client = LiteLLMClient(
            provider_id="mimo",
            protocol="anthropic",
            model="mimo-v2-flash",
            api_key="secret",
            base_url=None,
        )
        text, meta = client.generate_with_instruction("hello", "reply with ok")

    assert text == "ok"
    assert meta["request_id"] == "req-1"
    llm.completion.assert_called_once()
    kwargs = llm.completion.call_args.kwargs
    assert kwargs["model"] == "anthropic/mimo-v2-flash"
    assert kwargs["api_key"] == "secret"
    assert kwargs["api_base"] == "https://api.xiaomimimo.com/v1"
