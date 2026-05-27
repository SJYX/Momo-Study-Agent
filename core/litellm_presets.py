"""core/litellm_presets.py: 供应商/模型预设数据。

10 家主流中英文 AI 供应商的 LiteLLM prefix、预设模型列表、是否需要 base_url。
"""
from __future__ import annotations

from typing import Optional

PROVIDERS: list[dict] = [
    {
        "id": "mimo",
        "name": "Mimo",
        "prefix": "openai/",
        "needs_base_url": True,
        "default_base_url": "https://api.xiaomimimo.com/v1",
        "models": ["mimo-v2-flash", "mimo-v2-pro"],
    },
    {
        "id": "gemini",
        "name": "Gemini",
        "prefix": "gemini/",
        "needs_base_url": False,
        "default_base_url": None,
        "models": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "prefix": "openai/",
        "needs_base_url": False,
        "default_base_url": None,
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1-nano"],
    },
    {
        "id": "anthropic",
        "name": "Claude",
        "prefix": "claude/",
        "needs_base_url": False,
        "default_base_url": None,
        "models": ["claude-sonnet-4-20250514", "claude-haiku-4-20250414"],
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "prefix": "deepseek/",
        "needs_base_url": False,
        "default_base_url": None,
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    {
        "id": "qwen",
        "name": "Qwen",
        "prefix": "openai/",
        "needs_base_url": True,
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-turbo", "qwen-max"],
    },
    {
        "id": "zhipu",
        "name": "Zhipu",
        "prefix": "openai/",
        "needs_base_url": True,
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-flash", "glm-4-plus", "glm-4-long"],
    },
    {
        "id": "moonshot",
        "name": "Moonshot",
        "prefix": "openai/",
        "needs_base_url": True,
        "default_base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
    },
    {
        "id": "yi",
        "name": "Yi",
        "prefix": "openai/",
        "needs_base_url": True,
        "default_base_url": "https://api.lingyiwanwu.com/v1",
        "models": ["yi-lightning", "yi-large", "yi-medium"],
    },
    {
        "id": "mistral",
        "name": "Mistral",
        "prefix": "mistral/",
        "needs_base_url": False,
        "default_base_url": None,
        "models": ["mistral-small-latest", "mistral-large-latest", "codestral-latest"],
    },
]

_PROVIDER_MAP = {p["id"]: p for p in PROVIDERS}


def get_models_for_provider(provider_id: str) -> list[str]:
    """返回供应商的预设模型列表，未知供应商返回空列表。"""
    p = _PROVIDER_MAP.get(provider_id)
    return list(p["models"]) if p else []


def get_default_base_url(provider_id: str) -> Optional[str]:
    """返回供应商的默认 base_url，不需要则返回 None。"""
    p = _PROVIDER_MAP.get(provider_id)
    return p["default_base_url"] if p else None


def get_provider_prefix(provider_id: str) -> str:
    """返回供应商的 LiteLLM prefix，如 'openai/'、'gemini/'。"""
    p = _PROVIDER_MAP.get(provider_id)
    return p["prefix"] if p else "openai/"


def needs_base_url(provider_id: str) -> bool:
    """返回供应商是否需要 base_url。"""
    p = _PROVIDER_MAP.get(provider_id)
    return p["needs_base_url"] if p else False


__all__ = [
    "PROVIDERS",
    "get_models_for_provider",
    "get_default_base_url",
    "get_provider_prefix",
    "needs_base_url",
]
