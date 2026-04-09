import os
import json
import google.generativeai as genai

class GeminiClient:
    def __init__(self, api_key: str, prompt_file: str = "gem_prompt.md"):
        genai.configure(api_key=api_key)
        self.prompt_file = prompt_file
        self.model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=self._load_instruction()
        )

    def _load_instruction(self) -> str:
        if not os.path.exists(self.prompt_file):
            return "你是一个高效的单词助记助手，请用简短有趣的谐音或者词根给下面的单词一句话建立联系。"
        with open(self.prompt_file, "r", encoding="utf-8") as f:
            return f.read().strip()

    def generate_mnemonics(self, words_batch: list) -> list:
        prompt = f"""
        我给你 {len(words_batch)} 个英语单词。请按系统设定为每个词生成一句绝妙助记法。
        请严格以 JSON 数组格式原样返回，包含 spelling 和 mnemonic 两项，不要有其余任何解释文字：
        [
            {{"spelling": "单词1", "mnemonic": "助记1"}},
            {{"spelling": "单词2", "mnemonic": "助记2"}}
        ]

        待处理单词列表: {", ".join(words_batch)}
        """
        try:
            response = self.model.generate_content(prompt)
            text = response.text.strip()
            
            # 清洗包裹的 Markdown 字符
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
                
            return json.loads(text.strip())
        except Exception as e:
            print(f"  [AI请求异常/数据不规范]: {e}")
            if 'response' in locals():
                print(f"  [被舍弃的错误返回文为]:\n{response.text}")
            return []
