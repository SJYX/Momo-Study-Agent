import sys
import io
import time
import os

# ── 路径修正 ──────────────────────────────────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from config import MOMO_TOKEN, GEMINI_API_KEY, TEST_DB_PATH, DB_PATH
from compat.maimemo_api import MaiMemoAPI
from compat.gemini_client import GeminiClient
from db_manager import init_db, save_ai_word_note, mark_processed

# 终端编码修正 (Windows 友好)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def run_apple_test(dry_run: bool = True):
    """
    针对单词 'apple' 执行全流程实战测试。
    """
    db_path = TEST_DB_PATH if dry_run else DB_PATH
    mode_name = "【安全模拟】" if dry_run else "【真实同步】"
    
    print(f"====== {mode_name} 启动 'apple' 实战测试 ======")
    init_db(db_path)
    
    momo = MaiMemoAPI(MOMO_TOKEN)
    gemini = GeminiClient(GEMINI_API_KEY)
    
    word = "apple"
    
    # 1. 获取 voc_id
    print(f"[*] 步骤 1: 获取 '{word}' 的 voc_id...")
    voc_res = momo.get_vocabulary(word)
    if not voc_res or not voc_res.get("success"):
        print(f"  [Error] 无法获取 '{word}' 资料。")
        return
        
    voc_data = voc_res.get("data", {}).get("voc", {})
    voc_id = voc_data.get("id")
    if not voc_id:
        print(f"  [Error] 未发现 voc_id。")
        return
    print(f"  ┗ ✅ voc_id: {voc_id}")
    
    # 2. AI 解析
    print(f"[*] 步骤 2: 请求 AI 解析...")
    ai_results = gemini.generate_mnemonics([word])
    if not ai_results:
        print(f"  [Error] AI 返回为空。")
        return
        
    payload = ai_results[0]
    print(f"  ┗ ✅ AI 解析成功")
    
    # 3. 存储
    print(f"[*] 步骤 3: 写入本地库 ({os.path.basename(db_path)})...")
    save_ai_word_note(voc_id, payload, db_path=db_path)
    print(f"  ┗ ✅ 存储成功")
    
    # 4. 同步
    print(f"[*] 步骤 4: 同步至墨墨...")
    if not dry_run:
        brief_note = f"{payload.get('basic_meanings','')}\n[IELTS] {payload.get('ielts_focus','')}"
        success = momo.sync_interpretation(voc_id, brief_note, tags=["雅思"])
        if success:
            mark_processed(voc_id, word, db_path=db_path)
            print(f"  ┗ ✅ 墨墨同步成功！")
        else:
            print(f"  ┗ ❌ 墨墨同步失败。")
    else:
        print(f"  ┗ [跳过] 安全模式，未执行真实同步。")

    print("\n====== 测试任务结束 ======")

if __name__ == "__main__":
    # 默认先跑安全模式
    run_apple_test(dry_run=True)
