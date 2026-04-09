import os
import json
import time
from google import genai
from google.genai import types

# 遇到 503/429 等临时错误时的重试配置
_MAX_RETRIES   = 3
_RETRY_WAIT_S  = [10, 25, 60]   # 三次重试等待秒数（指数退避）

class GeminiClient:
    def __init__(self, api_key: str, model_name: str = None, prompt_file: str = "gem_prompt.md"):
        self.client = genai.Client(api_key=api_key)
        self.prompt_file = prompt_file
        # 优先级：参数指定 > 环境变量 > 默认模型
        self.model_name = model_name or os.getenv("GEMINI_MODEL") or "gemini-3-flash-preview"

    def _load_instruction(self) -> str:
        if not os.path.exists(self.prompt_file):
            return "你是一个高效的单词助记助手，请用简短有趣的谐音或者词根给下面的单词一句话建立联系。"
        with open(self.prompt_file, "r", encoding="utf-8") as f:
            return f.read().strip()

    def generate_mnemonics(self, words_batch: list) -> list:
        prompt = f"""
        请处理以下 {len(words_batch)} 个英语单词，严格遵循系统设定中的全维度 JSON 数组格式返回分析：
        待处理单词列表: {", ".join(words_batch)}
        """
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self._load_instruction()
                    )
                )
                text = response.text.strip()

                # 清洗包裹的 Markdown 字符
                if text.startswith("```json"):
                    text = text[7:]
                elif text.startswith("```"):
                    text = text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

                # 鲁棒修复：用括号计数找出第一个合法结束的 JSON 数组范围，
                # 截断模型可能在 ] 后追加的任意乱码（如 ]道路]）。
                text = _extract_json_array(text)

                return json.loads(text)

            except Exception as e:
                err_msg = str(e)
                is_transient = any(code in err_msg for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))

                if is_transient and attempt < _MAX_RETRIES:
                    wait = _RETRY_WAIT_S[attempt - 1]
                    print(f"  [RETRY {attempt}/{_MAX_RETRIES}] {err_msg[:120]} (waiting {wait}s)")
                    time.sleep(wait)
                    continue

                # 不可恢复 或 已用完重试
                print(f"  [AI请求异常/数据不规范]: {e}")
                if 'response' in locals():
                    print(f"  [被舍弃的错误返回文为]:\n{response.text}")
                return []

def _extract_json_array(text: str) -> str:
    """
    从字符串中提取第一个完整的 JSON 数组 [...]。
    使用括号计数器来确定结束位置，防止末尾乱码干扰。
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
                return text[start : i + 1]
    return text[start:]
