import traceback
import sys
import io
import time
import os
from dotenv import load_dotenv

from maimemo_api import MaiMemoAPI
from db_manager import init_db, is_processed, mark_processed
from gemini_client import GeminiClient

# 解决终端中文的输出乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# 加载 .env 变量
load_dotenv()

MOMO_TOKEN = os.getenv("MOMO_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 【安全开关】
DRY_RUN = True
# 【仅仅处理新词开关】
ONLY_PROCESS_NEW = False

def chunk_list(lst, chunk_size):
    for i in range(0, len(lst), chunk_size):
        yield lst[i:i + chunk_size]

def main():
    print("====== 🚀 启动极简全自动背单词黑科技流 (SQLite去重版) ======")
    init_db()
    
    if not MOMO_TOKEN or not GEMINI_API_KEY:
        print("[错误] 未在 .env 文件中发现有效的 MOMO_TOKEN 或 GEMINI_API_KEY！请检查 .env 是否配置好！")
        return

    gem_client = GeminiClient(GEMINI_API_KEY)
    momo = MaiMemoAPI(MOMO_TOKEN)
    
    res = momo.get_today_items()
    if not res or not res.get("success"):
        print("[错误] 墨墨背单词接口数据抓取挫败，请检查网络和Token！")
        return
        
    all_items = res.get("data", {}).get("today_items", [])
    print(f"[*] 从墨墨拉取到 {len(all_items)} 个待复习原始单词。")
    
    # 获取需要处理的干净词汇表（过滤老词、过滤已经落库的词）
    word_dict = {}
    db_skipped_count = 0
    
    for item in all_items:
        spelling = item.get("voc_spelling")
        voc_id = item.get("voc_id")
        
        if ONLY_PROCESS_NEW and not item.get("is_new", False):
            continue
            
        if is_processed(voc_id):
            db_skipped_count += 1
            continue
            
        word_dict[spelling] = voc_id
        
    target_words = list(word_dict.keys())
    print(f"[*] SQLite 去重过滤了 {db_skipped_count} 个历史查重词。")
    print(f"[*] 本次真正需要送向 Gemini 处理的新单词共计 {len(target_words)} 个。\n")
    
    if not target_words:
        print("🎉 太棒了，当前没有任何生词需要 AI 紧急救援！")
        return
        
    BATCH_SIZE = 15
    batches = list(chunk_list(target_words, BATCH_SIZE))
    
    for idx, batch in enumerate(batches):
        print(f"---> 开始向 Gemini 请求第 {idx+1}/{len(batches)} 批次 (约 {len(batch)} 词)...")
        
        ai_results = gem_client.generate_mnemonics(batch)
        
        if not ai_results:
            print("[警告] 本批次生成异常全军覆没或解析错位，跳过此批次。")
            continue
            
        for ai_item in ai_results:
            w_spell = ai_item.get("spelling", "")
            mnemonic = ai_item.get("mnemonic", "")
            w_id = word_dict.get(w_spell)
            
            if w_id and mnemonic:
                print(f"  > [💡AI 妙语] {w_spell}: {mnemonic}")
                
                if not DRY_RUN:
                    time.sleep(0.5) 
                    # 将这句助记作为 `AI专供助记` 分类创建进笔记薄中
                    success = momo.create_note(w_id, "AI专供", mnemonic)
                    if success:
                        print("    ┗ ✅ [入库同步] -> 墨墨端已可见")
                        mark_processed(w_id, w_spell) # 标记入库，下次不再处理
                    else:
                        print("    ┗ ❌ [入库同步] -> 写入失败")
        
        # 防止过高频调用导致 Gemini 限流
        if idx < len(batches) - 1:
            time.sleep(4)

    print("\n====== 🎉 全线任务打卡结束 ======")
    if DRY_RUN:
        print("\n⚠️ 提示：当前系统工作在安全模拟 (DRY RUN) 模式。")
        print("未向墨墨真实写入任何数据，也没有标记数据库。")
        print("修改 main.py 中的 DRY_RUN = False 即可大开杀戒真实写入并留档 SQLite！")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[中止] 用户手动退出了程序。")
    except Exception as e:
        print(f"\n[崩溃] 代码运行发生了致命异常：{e}")
        traceback.print_exc()
