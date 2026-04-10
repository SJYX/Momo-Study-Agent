from typing import Tuple, Dict, Any, List
import os
import json
import time
from google import genai
from google.genai import types
from config import GEMINI_MODEL, MAX_RETRIES, RETRY_WAIT_S, PROMPT_FILE
import sys

# 终端编码修正已移至入口脚本 (main.py) 中

class GeminiClient:
    def __init__(self, api_key: str, model_name: str = None, prompt_file: str = None):
        self.client = genai.Client(api_key=api_key)
        self.prompt_file = prompt_file or PROMPT_FILE
        self.model_name = model_name or GEMINI_MODEL

    def _load_instruction(self) -> str:
        if not os.path.exists(self.prompt_file):
            return "你是一个高效的单词助记助手，请分析给定的单词。"
        with open(self.prompt_file, "r", encoding="utf-8") as f:
            return f.read().strip()

    def generate_with_instruction(self, prompt: str, instruction: str = None) -> Tuple[str, dict]:
        """通用生成方法，支持自定义指令。"""
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
        请处理以下 {len(words_batch)} 个英语单词，严格遵循系统设定中的全维度 JSON 数组格式返回分析：
        待处理单词列表: {", ".join(words_batch)}
        """
        text, metadata = self.generate_with_instruction(prompt)
        if not text:
            return [], {}
            
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
            
            results = json.loads(text)
            # 为每个结果项记录其自身的原始 JSON（而非整个 batch 字符串）
            for item in results:
                item['raw_full_text'] = json.dumps(item, ensure_ascii=False)
            return results, metadata
        except Exception as e:
            print(f"  [JSON Parse Error]: {str(e)[:120]}")
            return [], {}

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
