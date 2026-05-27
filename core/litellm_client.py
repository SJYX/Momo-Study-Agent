"""core/litellm_client.py: 统一 AI 客户端，封装 litellm.completion()。

替换 MimoClient / GeminiClient，接口保持 generate_with_instruction(prompt, instruction)。
"""
from __future__ import annotations

import os
import time
from typing import Tuple

import litellm

from config import MAX_RETRIES, PROMPT_FILE, RETRY_WAIT_S

# 抑制 litellm 自身的重试日志（我们自己管理重试）
litellm.suppress_debug_info = True


class LiteLLMClient:
    """统一 AI 客户端，支持 10+ 供应商。"""

    def __init__(self, model: str, api_key: str, base_url: str = None):
        if not api_key:
            raise ValueError("API key is required")
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.prompt_file = PROMPT_FILE

    def _load_instruction(self) -> str:
        """加载系统提示词。"""
        if not os.path.exists(self.prompt_file):
            return "你是一个高效的单词助记助手，请分析给定的单词。"
        with open(self.prompt_file, "r", encoding="utf-8") as f:
            return f.read().strip()

    def generate_with_instruction(
        self, prompt: str, instruction: str = None
    ) -> Tuple[str, dict]:
        """调用 litellm.completion()，返回 (text, usage_dict)。"""
        system_instr = instruction or self._load_instruction()
        messages = [
            {"role": "system", "content": system_instr},
            {"role": "user", "content": prompt},
        ]

        kwargs = {
            "model": self.model,
            "messages": messages,
            "api_key": self.api_key,
        }
        if self.base_url:
            kwargs["api_base"] = self.base_url

        last_error = ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = litellm.completion(**kwargs)
                choice = response.choices[0]
                text = choice.message.content or ""
                usage = response.usage

                metadata = {
                    "request_id": getattr(response, "id", None),
                    "finish_reason": choice.finish_reason,
                    "prompt_tokens": usage.prompt_tokens if usage else 0,
                    "completion_tokens": usage.completion_tokens if usage else 0,
                    "total_tokens": usage.total_tokens if usage else 0,
                }
                return text.strip(), metadata
            except Exception as e:
                last_error = str(e)
                try:
                    from core.logger import get_logger
                    get_logger().warning(
                        "LiteLLM 请求失败，准备重试",
                        module="litellm_client",
                        attempt=attempt,
                        max_retries=MAX_RETRIES,
                        error=last_error,
                    )
                except Exception:
                    pass
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_WAIT_S[attempt - 1])
                    continue

        return "", {
            "error": last_error,
            "error_type": "request",
            "stage": "request",
        }

    def close(self):
        """清理资源（litellm 无状态，保留接口兼容）。"""
        pass


__all__ = ["LiteLLMClient"]
