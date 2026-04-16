from typing import Tuple, Dict, Any, List
import os
import json
import time
import json_repair
from config import GEMINI_MODEL, MAX_RETRIES, RETRY_WAIT_S, PROMPT_FILE
import sys

# 终端编码修正已移至入口脚本 (main.py) 中

class GeminiClient:
    def __init__(self, api_key: str, model_name: str = None, prompt_file: str = None):
        from google import genai
        self.client = genai.Client(api_key=api_key)
        self.prompt_file = prompt_file or PROMPT_FILE
        self.model_name = model_name or GEMINI_MODEL

    def close(self):
        """统一释放底层 HTTP 资源。"""
        close = getattr(self.client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def _load_instruction(self) -> str:
        if not os.path.exists(self.prompt_file):
            return "你是一个高效的单词助记助手，请分析给定的单词。"
        with open(self.prompt_file, "r", encoding="utf-8") as f:
            return f.read().strip()

    def generate_with_instruction(self, prompt: str, instruction: str = None) -> Tuple[str, dict]:
        """通用生成方法，支持自定义指令。"""
        from google.genai import types
        instr = instruction or self._load_instruction()
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=instr
                    )
                )
                text = response.text.strip()
                usage = response.usage_metadata
                
                metadata = {
                    "request_id": None,
                    "finish_reason": str(response.candidates[0].finish_reason) if response.candidates else "UNKNOWN",
                    "prompt_tokens": usage.prompt_token_count if usage else 0,
                    "completion_tokens": usage.candidates_token_count if usage else 0,
                    "total_tokens": usage.total_token_count if usage else 0
                }
                return text, metadata
            except Exception as e:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_WAIT_S[attempt-1])
                    continue
                return "", {}

    def generate_mnemonics(self, words_batch: list) -> Tuple[list, dict]:
        prompt = f"""
        请处理以下 {len(words_batch)} 个英语单词，严格遵循系统设定中的全维度分析。
        你必须直接返回一个 JSON 数组（[...]）。
        绝对不要返回 {{"results": [...]}} 或任何对象包裹结构。
        输出中不要包含 Markdown 代码块标记（如 ```json 或 ```）。
        请确保输出是语法完全合法的 JSON。
        待处理单词列表: {", ".join(words_batch)}
        """
        text, metadata = self.generate_with_instruction(prompt)
        if not text:
            meta = metadata or {}
            meta.setdefault("stage", "request")
            return [], meta
            
        try:
            # 清洗包裹的 Markdown 字符
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            # 鲁棒修复：用括号计数找出第一个合法结束的 JSON 数组范围
            text = _extract_json_array(text)
            
            data = json_repair.loads(text)
            results = []
            if isinstance(data, list):
                results = data

            # 备份单词自身的原始内容（在注入 token 统计前先捕获，保持纯粹的 AI 输出）
            n = len(results) if len(results) > 0 else 1
            for item in results:
                item['raw_full_text'] = json.dumps(item, ensure_ascii=False)
                # 均摊 tokens（展示用，不影响存档内容）
                if metadata:
                    item["prompt_tokens"] = metadata.get('prompt_tokens', 0) // n
                    item["completion_tokens"] = metadata.get('completion_tokens', 0) // n
                    item["total_tokens"] = metadata.get('total_tokens', 0) // n
            
            return results, metadata
        except Exception as e:
            preview = text[:500] if text else ""
            try:
                from core.logger import get_logger
                get_logger().error(
                    "[JSON Parse Error]",
                    error=str(e),
                    module="gemini_client",
                    words_count=len(words_batch),
                    response_preview=preview,
                )
            except:
                print(f"  [Gemini Parse Error]: {str(e)[:120]}")
            return [], {
                "error": str(e),
                "error_type": type(e).__name__,
                "stage": "parse",
            }

def _extract_json_array(text: str) -> str:
    """从字符串中提取第一个完整的 JSON 数组 [...]，防止末尾乱码干扰。"""
    start = text.find("[")
    if start == -1: return text
    
    count = 0
    for i in range(start, len(text)):
        if text[i] == "[": count += 1
        elif text[i] == "]":
            count -= 1
            if count == 0: return text[start : i+1]
    return text[start:]
