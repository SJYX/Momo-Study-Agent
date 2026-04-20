# -*- coding: utf-8 -*-
import sys
import os
import sqlite3

# 修正工作目录
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from core.maimemo_api import MaiMemoAPI
from config import MOMO_TOKEN
from config import DB_PATH
from database.utils import clean_for_maimemo

def rollback():
    print("🚀 [Rollback] Starting to fix incorrect interpretations in MaiMemo...")
    
    if not MOMO_TOKEN or "your_momo_token" in MOMO_TOKEN:
        print("❌ Error: MOMO_TOKEN is not configured correctly in .env")
        return

    momo = MaiMemoAPI(MOMO_TOKEN)
    
    # 1. 连接数据库获取今天生成的词
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    print(f"  [*] Checking history.db at: {DB_PATH}")
    # 获取今天处理的所有单词
    cur.execute("SELECT voc_id, spelling, basic_meanings FROM ai_word_notes WHERE created_at >= date('now', 'localtime')")
    rows = cur.fetchall()
    
    if not rows:
        print("  [Info] No words found matching today's timestamp. Maybe check UTC vs Local?")
        # 尝试不带 localtime 的查询作为兜底
        cur.execute("SELECT voc_id, spelling, basic_meanings FROM ai_word_notes WHERE created_at >= date('now')")
        rows = cur.fetchall()

    print(f"  [Info] Found {len(rows)} words to roll back.")

    success_count = 0
    fail_count = 0

    for row in rows:
        voc_id = row['voc_id']
        spelling = row['spelling']
        # 仅取基本释义，并进行清洗
        clean_intp = clean_for_maimemo(row['basic_meanings'])
        
        print(f"  ⏳ Fixing '{spelling}' (ID: {voc_id})...")
        
        try:
            # sync_interpretation 会自动查找并更新已有释义
            # 我们在这里强制推送，不管它以前长什么样，直接覆盖为干净的基本释义
            success = momo.sync_interpretation(voc_id, clean_intp, tags=["雅思"])
            if success:
                print(f"    ✅ '{spelling}' updated successfully.")
                success_count += 1
            else:
                print(f"    ❌ '{spelling}' update failed (API returned failure).")
                fail_count += 1
        except Exception as e:
            print(f"    ⚠️ '{spelling}' error: {e}")
            fail_count += 1

    conn.close()
    
    print(f"\n✨ [Finish] Rollback Complete!")
    print(f"   - Total processed: {len(rows)}")
    print(f"   - Success: {success_count}")
    print(f"   - Failed: {fail_count}")

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    rollback()
