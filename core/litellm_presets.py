"""core/litellm_presets.py: provider + protocol registry for LiteLLM.

This module centralizes provider metadata including supported protocols,
default protocol, protocol-specific model prefixes, default base_url and models.
"""
from __future__ import annotations

from typing import Optional

PROVIDERS: list[dict] = [
    {
        "id": "mimo",
        "name": "Mimo",
        "default_protocol": "openai",
        "supported_protocols": ["openai", "anthropic"],
        "protocol_prefixes": {"openai": "openai/", "anthropic": "anthropic/"},
        "default_base_url": "https://api.xiaomimimo.com/v1",
        "models": ["mimo-v2-flash", "mimo-v2-pro"],
    },
    {
        "id": "gemini",
        "name": "Gemini",
        "default_protocol": "gemini",
        "supported_protocols": ["gemini"],
        "protocol_prefixes": {"gemini": "gemini/"},
        "default_base_url": None,
        "models": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "default_protocol": "openai",
        "supported_protocols": ["openai"],
        "protocol_prefixes": {"openai": "openai/"},
        "default_base_url": None,
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1-nano"],
    },
    {
        "id": "anthropic",
        "name": "Claude",
        "default_protocol": "anthropic",
        "supported_protocols": ["anthropic"],
        "protocol_prefixes": {"anthropic": "claude/"},
        "default_base_url": None,
        "models": ["claude-sonnet-4-20250514", "claude-haiku-4-20250414"],
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "default_protocol": "openai",
        "supported_protocols": ["openai"],
        "protocol_prefixes": {"openai": "deepseek/"},
        "default_base_url": None,
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    {
        "id": "qwen",
        "name": "Qwen",
        "default_protocol": "openai",
        "supported_protocols": ["openai"],
        "protocol_prefixes": {"openai": "openai/"},
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-turbo", "qwen-max"],
    },
    {
        "id": "zhipu",
        "name": "Zhipu",
        "default_protocol": "openai",
        "supported_protocols": ["openai"],
        "protocol_prefixes": {"openai": "openai/"},
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-flash", "glm-4-plus", "glm-4-long"],
    },
    {
        "id": "moonshot",
        "name": "Moonshot",
        "default_protocol": "openai",
        "supported_protocols": ["openai"],
        "protocol_prefixes": {"openai": "openai/"},
        "default_base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
    },
    {
        "id": "yi",
        "name": "Yi",
        "default_protocol": "openai",
        "supported_protocols": ["openai"],
        "protocol_prefixes": {"openai": "openai/"},
        "default_base_url": "https://api.lingyiwanwu.com/v1",
        "models": ["yi-lightning", "yi-large", "yi-medium"],
    },
    {
        "id": "mistral",
        "name": "Mistral",
        "default_protocol": "mistral",
        "supported_protocols": ["mistral"],
        "protocol_prefixes": {"mistral": "mistral/"},
        "default_base_url": None,
        "models": ["mistral-small-latest", "mistral-large-latest", "codestral-latest"],
    },
]


_PROVIDER_MAP = {provider["id"]: provider for provider in PROVIDERS}


def _provider(provider_id: str) -> dict | None:
    return _PROVIDER_MAP.get(provider_id)


def get_models_for_provider(provider_id: str) -> list[str]:
    provider = _provider(provider_id)
    return list(provider["models"]) if provider else []


def get_supported_protocols(provider_id: str) -> list[str]:
    provider = _provider(provider_id)
    return list(provider["supported_protocols"]) if provider else []


def get_default_protocol(provider_id: str) -> Optional[str]:
    provider = _provider(provider_id)
    return provider["default_protocol"] if provider else None


def get_default_base_url(provider_id: str) -> Optional[str]:
    provider = _provider(provider_id)
    return provider.get("default_base_url") if provider else None


def get_provider_prefix(provider_id: str, protocol: str | None = None) -> str:
    provider = _provider(provider_id)
    if not provider:
        return "openai/"
    selected_protocol = protocol or provider["default_protocol"]
    prefixes = provider.get("protocol_prefixes", {})
    return prefixes.get(selected_protocol, prefixes.get(provider["default_protocol"], "openai/"))


__all__ = [
    "PROVIDERS",
    "get_models_for_provider",
    "get_supported_protocols",
    "get_default_protocol",
    "get_default_base_url",
    "get_provider_prefix",
]
