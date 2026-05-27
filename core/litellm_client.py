"""core/litellm_client.py: 统一 AI 客户端，封装 litellm.completion()。

替换 MimoClient / GeminiClient，接口保持 generate_with_instruction(prompt, instruction)。
"""
from __future__ import annotations

import json
import os
import time
from typing import Tuple

import json_repair
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

    def generate_mnemonics(self, words_batch: list) -> Tuple[list, dict]:
        """生成助记法，返回 JSON 数组格式。"""
        prompt = f"""
        请处理以下 {len(words_batch)} 个英语单词，严格遵循系统设定中的全维度分析。
        必须返回标准的 JSON 对象结构：{{"results": [...]}}，将结果放入名为 "results" 的数组中。
        【极其重要】：请确保输出是语法完全合法的 JSON！如果中文字段内需要使用标点符号侧重点，请一律使用单引号或中文引号。绝对不要在字符串值中出现未转义的英文双引号。
        输出中不要包含 Markdown 代码块标记（如 ```json 或 ```）。
        待处理单词列表: {", ".join(words_batch)}
        """
        text, metadata = self.generate_with_instruction(prompt)
        if not text:
            meta = metadata or {}
            meta.setdefault("stage", "request")
            return [], meta

        try:
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            data = json_repair.loads(text)
            results = []
            if isinstance(data, dict):
                results = data.get("results", [])
            elif isinstance(data, list):
                results = data

            final_results = []
            n = len(results)
            for item in results:
                if not isinstance(item, dict):
                    try:
                        from core.logger import get_logger
                        get_logger().warning(
                            "AI 返回了非对象类型的 JSON 条目，已跳过",
                            module="litellm_client",
                            item_type=type(item).__name__,
                            item_preview=str(item)[:100],
                        )
                    except Exception:
                        pass
                    continue

                cnt = n if n > 0 else 1
                item["raw_full_text"] = json.dumps(item, ensure_ascii=False)
                item["prompt_tokens"] = metadata.get("prompt_tokens", 0) // cnt
                item["completion_tokens"] = metadata.get("completion_tokens", 0) // cnt
                item["total_tokens"] = metadata.get("total_tokens", 0) // cnt
                final_results.append(item)

            return final_results, metadata
        except Exception as e:
            preview = text[:500] if text else ""
            try:
                from core.logger import get_logger
                get_logger().error(
                    "[JSON Parse Error]",
                    error=str(e),
                    module="litellm_client",
                    words_count=len(words_batch),
                    response_preview=preview,
                )
            except Exception:
                pass
            return [], {
                "error": str(e),
                "error_type": type(e).__name__,
                "stage": "parse",
            }

    def close(self):
        """清理资源（litellm 无状态，保留接口兼容）。"""
        pass


__all__ = ["LiteLLMClient"]
