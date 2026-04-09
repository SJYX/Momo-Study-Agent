import os
import json
import time
import requests
import json_repair
from config import MIMO_MODEL, MIMO_API_KEY, MIMO_API_BASE, MAX_RETRIES, RETRY_WAIT_S, PROMPT_FILE


class MimoClient:
    """小米 Mimo 模型客户端，兼容 OpenAI API 格式"""

    def __init__(self, api_key: str = None, model_name: str = None, prompt_file: str = None):
        self.api_key = api_key or MIMO_API_KEY
        self.model_name = model_name or MIMO_MODEL
        self.api_base = MIMO_API_BASE
        self.prompt_file = prompt_file or PROMPT_FILE

        if not self.api_key:
            raise ValueError("MIMO_API_KEY is required but not set")

    def _load_instruction(self) -> str:
        """加载系统提示词"""
        if not os.path.exists(self.prompt_file):
            return "你是一个高效的单词助记助手，请分析给定的单词。"
        with open(self.prompt_file, "r", encoding="utf-8") as f:
            return f.read().strip()

    def generate_mnemonics(self, words_batch: list) -> list:
        """生成助记法，返回 JSON 数组格式"""
        system_instruction = self._load_instruction()

        prompt = f"""
        请处理以下 {len(words_batch)} 个英语单词，严格遵循系统设定中的全维度分析，并将结果放入一个名为 "results" 的 JSON 数组中返回。
        必须返回标准的 JSON 对象结构：{{"results": [...]}}。
        【极其重要】：请确保输出是语法完全合法的 JSON！如果中文字段内需要使用标点符号侧重点，请一律使用单引号或中文引号。绝对不要在字符串值中出现未转义的英文双引号。
        待处理单词列表: {", ".join(words_batch)}
        """

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # 构建 OpenAI 兼容的请求格式
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }

                payload = {
                    "model": self.model_name,
                    "messages": [
                        {"role": "developer", "content": system_instruction},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7,
                    "max_completion_tokens": 64000, # 官方给定的单次暴发 64K 极大限制
                    "response_format": {"type": "json_object"},
                    "thinking": {"type": "disabled"}
                }

                response = requests.post(
                    f"{self.api_base}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60
                )

                if response.status_code != 200:
                    raise Exception(f"API Error {response.status_code}: {response.text}")

                result = response.json()
                text = result["choices"][0]["message"]["content"].strip()

                # 无论 JSON 是否合法，第一时间截获并记录账单
                usage = result.get("usage", {})
                self.last_usage = usage
                
                print(f"  🪙 [Token 消耗账单] Prompt: {usage.get('prompt_tokens', 0)} | " 
                      f"Completion: {usage.get('completion_tokens', 0)} | "
                      f"Total: {usage.get('total_tokens', 0)}")

                # 利用强大的启发式库解析破损的 JSON 对象并提取 results
                data = json_repair.loads(text)
                
                results = []
                if isinstance(data, dict):
                    results = data.get("results", [])
                elif isinstance(data, list):
                    # 防御：如果大模型彻底放飞自我，去掉了外层 results 的壳
                    results = data
                
                # 将这批次的整体花销均摊到本批次的每一个单词上供入库
                n = len(results) if len(results) > 0 else 1
                for item in results:
                    item["prompt_tokens"] = usage.get('prompt_tokens', 0) // n
                    item["completion_tokens"] = usage.get('completion_tokens', 0) // n
                    item["total_tokens"] = usage.get('total_tokens', 0) // n
                
                return results

            except Exception as e:
                err_msg = str(e)
                # 打印出来自底层的原始翻车文本方便查漏
                if "Expecting" in err_msg or "JSON Decode" in err_msg:
                    print(f"\n  [JSON 原生结构损坏] RAW Mimo Output:\n  {text}\n")
                # 判断是否为瞬时错误
                is_transient = any(code in err_msg for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "timeout", "Timeout"))

                if is_transient and attempt < MAX_RETRIES:
                    wait = RETRY_WAIT_S[attempt - 1]
                    print(f"  [RETRY {attempt}/{MAX_RETRIES}] {err_msg[:80]} (waiting {wait}s)")
                    time.sleep(wait)
                    continue

                print(f"  [Mimo Error]: {err_msg[:120]}")
                return []


def _extract_json_array(text: str) -> str:
    """从字符串中提取第一个完整的 JSON 数组 [...]，防止末尾乱码干扰"""
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


if __name__ == "__main__":
    # 测试代码
    try:
        client = MimoClient()
        print(f"Testing Mimo client with model: {client.model_name}")

        # 简单测试
        test_words = ["apple", "banana"]
        result = client.generate_mnemonics(test_words)
        print(f"Result: {json.dumps(result, ensure_ascii=False, indent=2)}")
    except Exception as e:
        print(f"Test failed: {e}")