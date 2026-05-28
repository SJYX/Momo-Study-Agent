from core.litellm_config import normalize_litellm_request


def test_normalize_adds_provider_prefix_once():
    req = normalize_litellm_request(
        provider_id="mimo",
        protocol="anthropic",
        model="mimo-v2-flash",
        api_key="key-1",
        base_url=None,
    )
    assert req.model == "anthropic/mimo-v2-flash"
    assert req.api_base == "https://api.xiaomimimo.com/v1"


def test_normalize_keeps_existing_prefixed_model():
    req = normalize_litellm_request(
        provider_id="mimo",
        protocol="openai",
        model="openai/mimo-v2-flash",
        api_key="key-1",
        base_url="https://proxy.example.com/v1",
    )
    assert req.model == "openai/mimo-v2-flash"
    assert req.api_base == "https://proxy.example.com/v1"


def test_unknown_protocol_is_rejected():
    try:
        normalize_litellm_request(
            provider_id="mimo",
            protocol="unknown",
            model="mimo-v2-flash",
            api_key="key-1",
            base_url=None,
        )
    except ValueError as exc:
        assert "unknown protocol" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")
