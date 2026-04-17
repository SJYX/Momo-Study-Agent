import os
import json
import time
import requests
import json_repair
from typing import Tuple, Dict, Any, List
from config import MIMO_MODEL, MIMO_API_KEY, MIMO_API_BASE, MAX_RETRIES, RETRY_WAIT_S, PROMPT_FILE


class MimoClient:
    """小米 Mimo 模型客户端，兼容 OpenAI API 格式"""

    def __init__(self, api_key: str = None, model_name: str = None, prompt_file: str = None):
        self.api_key = api_key or MIMO_API_KEY
        self.model_name = model_name or MIMO_MODEL
        self.api_base = MIMO_API_BASE
        self.prompt_file = prompt_file or PROMPT_FILE
        self.connect_timeout_s = float(os.getenv("MIMO_CONNECT_TIMEOUT_S", "10"))
        self.read_timeout_s = float(os.getenv("MIMO_READ_TIMEOUT_S", "60"))
        self.session = requests.Session()

        if not self.api_key:
            raise ValueError("MIMO_API_KEY is required but not set")

    def close(self):
        """统一清理入口；关闭复用连接池。"""
        self.session.close()

    def _load_instruction(self) -> str:
        """加载系统提示词"""
        if not os.path.exists(self.prompt_file):
            return "你是一个高效的单词助记助手，请分析给定的单词。"
        with open(self.prompt_file, "r", encoding="utf-8") as f:
            return f.read().strip()

    def generate_with_instruction(self, prompt: str, instruction: str = None) -> Tuple[str, dict]:
        """与 OpenAI 兼容的通用请求逻辑"""
        system_instr = instruction or self._load_instruction()
        last_error = ""
        last_error_type = ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                started_at = time.time()
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": self.model_name,
                    "messages": [
                        {"role": "developer", "content": system_instr},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7,
                    "max_completion_tokens": 64000,
                    "thinking": {"type": "disabled"}
                }
                # 针对 SSL 证书验证失败的容错处理
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

                try:
                    from core.logger import get_logger
                    get_logger().debug(
                        f"Mimo 请求开始: model={self.model_name}, attempt={attempt}/{MAX_RETRIES}, connect_timeout={self.connect_timeout_s}s, read_timeout={self.read_timeout_s}s",
                        module="mimo_client",
                    )
                except Exception:
                    pass
                
                response = self.session.post(
                    f"{self.api_base}/chat/completions", 
                    headers=headers, 
                    json=payload, 
                    timeout=(self.connect_timeout_s, self.read_timeout_s),
                    verify=False  # 临时跳过证书校验以解决 SSL 错误
                )
                if response.status_code != 200:
                    raise Exception(f"API Error {response.status_code}: {response.text}")

                result = response.json()
                text = result["choices"][0]["message"]["content"].strip()
                usage = result.get("usage", {})
                
                metadata = {
                    "request_id": result.get("id"),
                    "finish_reason": result["choices"][0].get("finish_reason"),
                    "prompt_tokens": usage.get('prompt_tokens', 0),
                    "completion_tokens": usage.get('completion_tokens', 0),
                    "total_tokens": usage.get('total_tokens', 0)
                }
                try:
                    from core.logger import get_logger
                    get_logger().debug(
                        f"Mimo 请求成功: attempt={attempt}/{MAX_RETRIES}, latency_ms={int((time.time()-started_at)*1000)}",
                        module="mimo_client",
                    )
                except Exception:
                    pass
                return text, metadata
            except Exception as e:
                last_error = str(e)
                last_error_type = type(e).__name__
                try:
                    from core.logger import get_logger
                    get_logger().warning(
                        f"Mimo 请求失败，准备重试 ({attempt}/{MAX_RETRIES})",
                        module="mimo_client",
                        attempt=attempt,
                        max_retries=MAX_RETRIES,
                        error=last_error,
                        error_type=last_error_type,
                    )
                except Exception:
                    pass
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_WAIT_S[attempt-1])
                    continue
                return "", {
                    "error": last_error,
                    "error_type": last_error_type,
                    "stage": "request",
                }

    def generate_mnemonics(self, words_batch: list) -> Tuple[list, dict]:
        """生成助记法，返回 JSON 数组格式"""
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
            # 清洗可能的 Markdown 包裹，再提取首个完整数组
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            text = _extract_json_array(text)

            data = json_repair.loads(text)
            results = []
            if isinstance(data, list):
                results = data
            
            # 备份单词自身的原始内容（在注入 token 统计前先捕获，保持纯粹的 AI 输出）
            n = len(results) if len(results) > 0 else 1
            for item in results:
                item['raw_full_text'] = json.dumps(item, ensure_ascii=False)
                # 均摔 tokens （展示用，不影响存档内容）
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
                    module="mimo_client",
                    words_count=len(words_batch),
                    response_preview=preview,
                )
            except:
                print(f"  [Mimo Parse Error]: {str(e)[:120]}")
            return [], {
                "error": str(e),
                "error_type": type(e).__name__,
                "stage": "parse",
            }


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