import os
import json
import io
import sys
import time
from dotenv import load_dotenv

from maimemo_api import MaiMemoAPI
from db_manager import init_db, is_processed, mark_processed
from gemini_client import GeminiClient

# 解决终端中文的输出乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

load_dotenv()
MOMO_TOKEN = os.getenv("MOMO_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def main():
    print("====== 🍎 启动 'apple' 全流程实战：分析 -> 入库 -> 同步墨墨 ======")
    init_db()
    
    if not MOMO_TOKEN or not GEMINI_API_KEY:
        print("[错误] 未在 .env 文件中发现有效的 MOMO_TOKEN 或 GEMINI_API_KEY！")
        return

    gem_client = GeminiClient(GEMINI_API_KEY)
    momo = MaiMemoAPI(MOMO_TOKEN)
    
    word = "apple"
    
    # 步骤 1: 获取 voc_id
    print(f"[*] 步骤 1: 正在从墨墨官方查询单词 '{word}' 的详细资料...")
    voc_res = momo.get_vocabulary(word)
    if not voc_res or not voc_res.get("success"):
        print(f"[错误] 无法查询到单词 '{word}'，可能是 Token 失效或网络问题。")
        return
    
    # 官方返回结构可能是 {"success": true, "data": {"vocabulary": {"id": "...", ...}}}
    # 需要根据实际返回结构提取
    voc_data = voc_res.get("data", {}).get("voc", {})
    voc_id = voc_data.get("id")
    if not voc_id:
        print(f"[错误] 解析返回数据失败，未找到 '{word}' 的 voc_id。原数据: {voc_res}")
        return
    
    print(f"    ┗ ✅ 成功获取 voc_id: {voc_id}")
    
    # 步骤 2: Gemini 分析
    print(f"[*] 步骤 2: 正在请求 Gemini ({gem_client.model_name}) 进行雅思考霸级分析...")
    ai_results = gem_client.generate_mnemonics([word])
    
    if not ai_results:
        print("[错误] Gemini 返回为空，请检查模型状态或网络。")
        return
    
    ai_item = ai_results[0]
    print(f"    ┗ ✅ AI 分析完成，已捕获结构化知识图谱。")
    
    # 步骤 3: 构造完整文本并入库
    print(f"[*] 步骤 3: 正在将知识图谱入库 (SQLite)...")
    
    raw_full_text = f"### {word}\n\n"
    raw_full_text += f"{ai_item.get('basic_meanings', '')}\n\n"
    raw_full_text += f"**[IELTS Focus]**\n{ai_item.get('ielts_focus', '')}\n\n"
    raw_full_text += f"**[Collocations]**\n{ai_item.get('collocations', '')}\n\n"
    raw_full_text += f"**[Traps]**\n{ai_item.get('traps', '')}\n\n"
    raw_full_text += f"**[Synonyms]**\n{ai_item.get('synonyms', '')}\n\n"
    raw_full_text += f"**[Discrimination]**\n{ai_item.get('discrimination', '')}\n\n"
    raw_full_text += f"**[Example Sentences]**\n{ai_item.get('example_sentences', '')}\n\n"
    raw_full_text += f"**[Memory Aid]**\n{ai_item.get('memory_aid', '')}\n\n"
    
    ai_item["raw_full_text"] = raw_full_text
    
    mark_processed(voc_id, ai_item)
    print(f"    ┗ ✅ SQLite 入库成功。")
    
    # 步骤 4: 同步到墨墨
    print(f"[*] 步骤 4: 正在同步到墨墨 (覆盖原生释义)...")
    momo_interpretation = ai_item.get('basic_meanings', '').strip()
    
    # 注意：这里我们使用 create_interpretation，如果已经存在可能会报错或覆盖，取决于墨墨 API 逻辑
    # 实际上 main.py 也是直接调用的 create_interpretation
    success = momo.sync_interpretation(voc_id, momo_interpretation, tags=["雅思"])
    
    if success:
        print("    ┗ ✅ [入库同步] -> 墨墨原生释义已升级重铸")
    else:
        print(f"    ┗ ❌ [入库同步] -> 写入失败。")

    print("\n====== 🎉 'apple' 全流程演示任务打卡结束 ======")

if __name__ == "__main__":
    main()
