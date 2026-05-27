"""core/litellm_client.py: 统一 AI 客户端，封装 litellm.completion()。

替换 MimoClient / GeminiClient，接口保持 generate_with_instruction(prompt, instruction)。
"""
from __future__ import annotations

import json
import os
import time
from typing import Tuple

import json_repair

from config import MAX_RETRIES, PROMPT_FILE, RETRY_WAIT_S

# litellm 延迟导入：模块级 import 耗时 ~13s，推迟到首次 API 调用时加载
_litellm = None
_litellm_configured = False


def _get_litellm():
    """延迟加载 litellm 并抑制调试日志。"""
    global _litellm, _litellm_configured
    if _litellm is None:
        import litellm as _m
        _litellm = _m
        if not _litellm_configured:
            _litellm.suppress_debug_info = True
            _litellm_configured = True
    return _litellm


def _extract_json_array(text: str) -> str:
    """从字符串中提取第一个完整的 JSON 数组 [...]，防止末尾乱码干扰。

    用括号计数找出第一个合法结束的数组范围。继承自旧 GeminiClient 的
    防御性恢复逻辑——json_repair 在多数情况已经鲁棒，但对 Gemini 这类
    容易在数组后追加散文的供应商，先做括号切片可减少 parse 失败率。
    """
    start = text.find("[")
    if start == -1:
        return text

    count = 0
    for i in range(start, len(text)):
        if text[i] == "[":
            count += 1
        elif text[i] == "]":
            count -= 1
            if count == 0:
                return text[start:i + 1]
    return text[start:]


class LiteLLMClient:
    """统一 AI 客户端，支持 10+ 供应商。"""

    def __init__(self, model: str, api_key: str, base_url: str = None):
        if not api_key:
            raise ValueError("API key is required")
        self.model = model
        # 兼容历史属性名：study_workflow 等调用方读 .model_name
        self.model_name = model
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

        # 旧 MimoClient 的核心生成参数——丢失会导致大批次被默认 max_tokens(~4096)截断。
        # 允许通过环境变量覆盖以适配不同供应商上限。
        try:
            temperature = float(os.getenv("AI_TEMPERATURE", "0.7"))
        except (TypeError, ValueError):
            temperature = 0.7
        try:
            max_tokens = int(os.getenv("AI_MAX_TOKENS", "64000"))
        except (TypeError, ValueError):
            max_tokens = 64000

        kwargs = {
            "model": self.model,
            "messages": messages,
            "api_key": self.api_key,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.base_url:
            kwargs["api_base"] = self.base_url

        last_error = ""
        last_error_type = ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                llm = _get_litellm()
                response = llm.completion(**kwargs)
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
                last_error_type = type(e).__name__
                try:
                    from core.logger import get_logger
                    get_logger().warning(
                        "LiteLLM 请求失败，准备重试",
                        module="litellm_client",
                        attempt=attempt,
                        max_retries=MAX_RETRIES,
                        error=last_error,
                        error_type=last_error_type,
                    )
                except Exception:
                    pass
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_WAIT_S[attempt - 1])
                    continue

        return "", {
            "error": last_error,
            # 保留原始异常类名而非硬编码 "request"——上游观测/重试逻辑可据此分流。
            "error_type": last_error_type or "request",
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
            text = text.strip()
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            # 防御：若供应商（典型如 Gemini）追加了散文/多余括号，
            # 先用括号计数切出第一个完整数组，再喂给 json_repair。
            # 仅在 text 像裸数组时才走这条路径——对 {"results": [...]} 包裹格式保留原文。
            if text.lstrip().startswith("["):
                text = _extract_json_array(text)

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
        """尽力释放 litellm 内部的 HTTP client 连接池。

        litellm 把 httpx 客户端缓存在 module-level；调 close_litellm_async_clients()
        会优雅关闭所有缓存。该函数仅在事件循环空闲时可调用，所以这里包了一层
        try/except 以保持调用方接口契约——任何异常都不外抛。
        """
        try:
            global _litellm
            if _litellm is None:
                return
            close_fn = getattr(_litellm, "close_litellm_async_clients", None)
            if not callable(close_fn):
                return
            try:
                import asyncio
                try:
                    asyncio.get_running_loop()
                    # 已在 event loop 内（异步 web 端点），由调用方负责 await。
                    return
                except RuntimeError:
                    asyncio.run(close_fn())
            except Exception:
                pass
        except Exception:
            pass


__all__ = ["LiteLLMClient"]
