"""core/factories.py: 业务对象工厂（DI 入口）。

Phase LiteLLM：统一使用 LiteLLMClient，不再按 provider 分支。
"""
from __future__ import annotations

from config import AI_API_KEY, AI_BASE_URL, AI_MODEL, AI_PROVIDER, AI_PROTOCOL
from core.litellm_client import LiteLLMClient


def build_ai_client() -> LiteLLMClient:
    """根据 config 当前配置构建统一 AI 客户端。

    Returns:
        LiteLLMClient

    Raises:
        ValueError: API key 缺失。
    """
    if not AI_API_KEY:
        raise ValueError(f"AI_API_KEY required (provider={AI_PROVIDER})")

    return LiteLLMClient(
        provider_id=AI_PROVIDER,
        protocol=AI_PROTOCOL,
        model=AI_MODEL or "",
        api_key=AI_API_KEY,
        base_url=AI_BASE_URL,
    )


__all__ = ["build_ai_client"]
