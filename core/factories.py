"""core/factories.py: 业务对象工厂（DI 入口）。

Phase LiteLLM：统一使用 LiteLLMClient，不再按 provider 分支。
"""
from __future__ import annotations

from config import AI_API_KEY, AI_BASE_URL, AI_MODEL, AI_PROVIDER
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

    # 构造 LiteLLM model 格式：provider/model
    model = AI_MODEL or ""
    if "/" not in model:
        # 自动加 prefix：gemini → gemini/xxx, mimo → openai/xxx
        from core.litellm_presets import get_provider_prefix
        prefix = get_provider_prefix(AI_PROVIDER)
        model = f"{prefix}{model}"

    return LiteLLMClient(
        model=model,
        api_key=AI_API_KEY,
        base_url=AI_BASE_URL,
    )


__all__ = ["build_ai_client"]
