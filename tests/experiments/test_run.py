import os
import json
import io
import sys
from dotenv import load_dotenv

# Add root directory to path so we can import project modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from compat.gemini_client import GeminiClient

# 解决终端中文的输出乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def main():
    print("====== 测试模型对于单词 'run' 的结构化分析能力 ======")
    if not GEMINI_API_KEY:
        print("[错误] 未找到 GEMINI_API_KEY")
        return
        
    client = GeminiClient(GEMINI_API_KEY)
    
    # 模拟我们传入的核心测试词
    test_words = ["run"]
    
    print(f"[*] 正在向 Gemini 发生解析请求: {test_words} ...")
    
    # 获取结果
    results = client.generate_mnemonics(test_words)
    
    if not results:
        print("[警告] 没有获取到返回结果，可能是格式异常。")
        return
        
    print("\n==== AI 提取的 JSON 数据体 ====\n")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    
    print("\n\n==== 模拟 main.py 的终端展示效果 ====\n")
    for ai_item in results:
        w_spell = ai_item.get("spelling", "")
        raw_full_text = f"### {w_spell}\n\n"
        raw_full_text += f"{ai_item.get('basic_meanings', '')}\n\n"
        raw_full_text += f"**[IELTS Focus]**\n{ai_item.get('ielts_focus', '')}\n\n"
        raw_full_text += f"**[Collocations]**\n{ai_item.get('collocations', '')}\n\n"
        raw_full_text += f"**[Traps]**\n{ai_item.get('traps', '')}\n\n"
        raw_full_text += f"**[Synonyms]**\n{ai_item.get('synonyms', '')}\n\n"
        raw_full_text += f"**[Discrimination]**\n{ai_item.get('discrimination', '')}\n\n"
        raw_full_text += f"**[Example Sentences]**\n{ai_item.get('example_sentences', '')}\n\n"
        raw_full_text += f"**[Memory Aid]**\n{ai_item.get('memory_aid', '')}\n\n"
        
        print(raw_full_text)

if __name__ == "__main__":
    main()
