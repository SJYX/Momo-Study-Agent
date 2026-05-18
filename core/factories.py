"""core/factories.py: 业务对象工厂（DI 入口）。

把 main.py 中的 AI 客户端构造函数搬到这里，让 main.py 只负责入口编排。

行为保持：
- AI_PROVIDER / MIMO_API_KEY / GEMINI_API_KEY 仍然走 module-level import，
  在 main.py 的 EARLY BOOTSTRAP 完成 config reload 之后被首次导入即可拿到正确值。
"""
from __future__ import annotations

from config import AI_PROVIDER, GEMINI_API_KEY, MIMO_API_KEY
from core.mimo_client import MimoClient


def build_ai_client():
    """根据 config 当前 AI_PROVIDER 选择 AI 客户端。

    返回：
        MimoClient 或 GeminiClient

    Raises:
        ValueError: 对应 provider 的 API key 缺失。
    """
    if AI_PROVIDER == "mimo":
        if not MIMO_API_KEY:
            raise ValueError("MIMO_API_KEY required")
        return MimoClient(MIMO_API_KEY)

    # 延迟导入：仅在选择 gemini 时加载
    from core.gemini_client import GeminiClient

    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY required")
    return GeminiClient(GEMINI_API_KEY)


__all__ = ["build_ai_client"]
