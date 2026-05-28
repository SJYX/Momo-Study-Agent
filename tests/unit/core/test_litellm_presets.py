from core.litellm_presets import (
    PROVIDERS,
    get_default_base_url,
    get_default_protocol,
    get_models_for_provider,
    get_supported_protocols,
    get_provider_prefix,
)


def test_mimo_exposes_multiple_protocols():
    assert get_supported_protocols("mimo") == ["openai", "anthropic"]
    assert get_default_protocol("mimo") == "openai"
    assert get_provider_prefix("mimo", "openai") == "openai/"
    assert get_provider_prefix("mimo", "anthropic") == "anthropic/"


def test_every_provider_has_a_default_protocol():
    for provider in PROVIDERS:
        protocols = get_supported_protocols(provider["id"]) 
        assert protocols
        assert get_default_protocol(provider["id"]) in protocols


def test_default_base_url_is_still_available():
    assert get_default_base_url("mimo") == "https://api.xiaomimimo.com/v1"
    assert "gemini-2.0-flash" in get_models_for_provider("gemini")
