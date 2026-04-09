import os
import json
import io
import sys
from dotenv import load_dotenv

# Add root directory to path so we can import project modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from gemini_client import GeminiClient

# 解决终端中文的输出乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def main():
    print("====== 实战操作：测试模型对于单词 'apple' 的结构化分析能力 ======")
    if not GEMINI_API_KEY:
        print("[错误] 未找到 GEMINI_API_KEY，请检查 .env 文件。")
        return
        
    client = GeminiClient(GEMINI_API_KEY)
    
    # 我们要测试的核心单词
    test_words = ["apple"]
    
    print(f"[*] 正在向 Gemini 发送解析请求: {test_words} ...")
    
    # 获取结果
    results = client.generate_mnemonics(test_words)
    
    if not results:
        print("[警告] 没有获取到返回结果，可能是格式异常。")
        return
        
    print("\n==== AI 提取的 JSON 数据体 ====\n")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    
    print("\n\n==== 终端展示格式化效果 ====\n")
    for ai_item in results:
        w_spell = ai_item.get("spelling", "")
        raw_full_text = f"### {w_spell}\n\n"
        
        # 处理 basic_meanings 可能包含的换行
        meanings = ai_item.get('basic_meanings', '').replace('\\n', '\n')
        raw_full_text += f"{meanings}\n\n"
        
        raw_full_text += f"**[IELTS Focus]**\n{ai_item.get('ielts_focus', '')}\n\n"
        raw_full_text += f"**[Collocations]**\n{ai_item.get('collocations', '')}\n\n"
        raw_full_text += f"**[Traps]**\n{ai_item.get('traps', '')}\n\n"
        raw_full_text += f"**[Synonyms]**\n{ai_item.get('synonyms', '')}\n\n"
        
        disc = ai_item.get('discrimination', '')
        if disc:
            raw_full_text += f"**[Discrimination]**\n{disc}\n\n"
            
        raw_full_text += f"**[Example Sentences]**\n{ai_item.get('example_sentences', '')}\n\n"
        raw_full_text += f"**[Memory Aid]**\n{ai_item.get('memory_aid', '')}\n\n"
        
        print(raw_full_text)

if __name__ == "__main__":
    main()
