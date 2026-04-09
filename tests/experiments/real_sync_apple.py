import sys
import os

# ── 路径修正 ──────────────────────────────────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from config import MOMO_TOKEN, DB_PATH
from maimemo_api import MaiMemoAPI
from db_manager import init_db, save_ai_word_note, mark_processed

# 终端编码修正 (Windows 友好)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def real_sync_apple():
    """
    【真实实战】手动构造解析数据，绕过 AI 限制，直接验证墨墨 API 写入与数据库持久化。
    """
    print(f"====== 🚀 正在执行 'apple' 真实同步实战测试 ======")
    init_db(DB_PATH)
    
    momo = MaiMemoAPI(MOMO_TOKEN)
    word = "apple"
    
    # 手动构造高质量解析数据 (模拟 AI 结果)
    ai_payload = {
        "spelling": "apple",
        "basic_meanings": "n. 苹果；苹果公司",
        "ielts_focus": "高频核心词。注意在雅思写作中可作为科技企业代名词或健康饮食话题词汇。",
        "collocations": "apple of one's eye (掌上明珠); Adam's apple (喉结)",
        "traps": "注意不要与 apply (申请) 混淆。在商业语境下常首字母大写指代 Apple Inc.",
        "synonyms": "N/A",
        "discrimination": "N/A",
        "example_sentences": "1. An apple a day keeps the doctor away. (一日一苹果，医生远离我。)\n2. We must compare apples to apples. (我们必须进行同类比较。)",
        "memory_aid": "词根记忆：ap- (趋向) + ple (充满) -> 充满水分的诱人果实。"
    }
    
    # 1. 获取真实 voc_id
    print(f"[*] 步骤 1: 获取 '{word}' 的真实 voc_id...")
    voc_res = momo.get_vocabulary(word)
    voc_id = voc_res.get("data", {}).get("voc", {}).get("id")
    
    if not voc_id:
        print("  [Error] 获取 voc_id 失败。")
        return
    print(f"  ┗ ✅ voc_id: {voc_id}")
    
    # 2. 写入正式数据库 (history.db)
    print(f"[*] 步骤 2: 写入正式库 history.db...")
    save_ai_word_note(voc_id, ai_payload, db_path=DB_PATH)
    print(f"  ┗ ✅ 本地持久化成功")
    
    # 3. 同步至墨墨云端
    print(f"[*] 步骤 3: 正在将深度解析同步至墨墨云端...")
    
    # 构造同步到 App 的精简释义
    brief_note = f"{ai_payload['basic_meanings']}\n[雅思核心] {ai_payload['ielts_focus']}"
    
    success = momo.sync_interpretation(voc_id, brief_note, tags=["雅思"])
    
    if success:
        mark_processed(voc_id, word, db_path=DB_PATH)
        print(f"\n✨ 🎉 【同步成功】")
        print(f"  - 单词: {word}")
        print(f"  - 状态: 已重铸为雅思级深度解析")
        print(f"  - 数据库: 已记录至 {os.path.basename(DB_PATH)}")
        print(f"\n请检查你的手机【墨墨背单词】App，'apple' 的释义应当已经更新。")
    else:
        print(f"\n❌ 【同步失败】请检查 Token 权限或网络连接。")

if __name__ == "__main__":
    real_sync_apple()
