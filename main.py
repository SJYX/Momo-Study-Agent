import sys
import io
import time
from config import MOMO_TOKEN, GEMINI_API_KEY, BATCH_SIZE, DRY_RUN
from maimemo_api import MaiMemoAPI
from gemini_client import GeminiClient
from db_manager import init_db, is_processed, mark_processed, save_ai_word_note

# 终端编码修正已移至 if __name__ == "__main__" 或入口函数中

class StudyFlowManager:
    """墨墨背单词 AI 助记主流程管理器。"""
    
    def __init__(self):
        self.momo = MaiMemoAPI(MOMO_TOKEN)
        self.gemini = GeminiClient(GEMINI_API_KEY)
        init_db()  # 初始化主库
        
    def run(self):
        print(f"🚀 [Start] 启动学习流 (DRY_RUN={DRY_RUN})")
        
        # 1. 获取今日单词
        res = self.momo.get_today_items(limit=100)
        if not res or not res.get("success"):
            print("  [Error] 无法获取今日单词列表。")
            return
            
        words = res["data"]["today_items"]
        print(f"  [Info] 今日待学单词共: {len(words)} 个")
        
        # 2. 过滤已处理单词
        pending_words = []
        for w in words:
            if not is_processed(w["voc_id"]):
                pending_words.append(w)
        
        if not pending_words:
            print("  [Finish] 所有单词均已解析过，流程结束。")
            return
            
        print(f"  [Info] 待解析新词: {len(pending_words)} 个")
        
        # 3. 按 BATCH_SIZE 进行批处理
        for i in range(0, len(pending_words), BATCH_SIZE):
            batch = pending_words[i : i + BATCH_SIZE]
            batch_spellings = [w["voc_spelling"] for w in batch]
            
            print(f"\n📦 [Batch] 正在处理批次 {i//BATCH_SIZE + 1} ({len(batch)} 词)...")
            
            # AI 生成
            ai_results = self.gemini.generate_mnemonics(batch_spellings)
            if not ai_results:
                print(f"  [Skip] 批次 {i//BATCH_SIZE + 1} AI 调用失败。")
                continue
                
            # 4. 结果对照并保存
            self._process_results(batch, ai_results)
            
            # 频率控制（保护 Gemini 和 Maimemo）
            if i + BATCH_SIZE < len(pending_words):
                print(f"⏳ 休息 10 秒后处理下一批...")
                time.sleep(10)

    def _process_results(self, batch_words, ai_results):
        """将 AI 结果映射回原始单词并持久化。"""
        # 转为字典加速查找
        ai_dict = {item["spelling"].lower(): item for item in ai_results}
        
        success_count = 0
        for w in batch_words:
            spell = w["voc_spelling"].lower()
            voc_id = w["voc_id"]
            
            if spell in ai_dict:
                payload = ai_dict[spell]
                
                # A. 写入本地库 (DB Isolation)
                save_ai_word_note(voc_id, payload)
                
                # B. 同步至墨墨 (Sync to Maimemo)
                if not DRY_RUN:
                    brief_note = f"{payload.get('basic_meanings','')}\n[IELTS] {payload.get('ielts_focus','')}"
                    self.momo.sync_interpretation(voc_id, brief_note, tags=["雅思"])
                
                # C. 标记已处理 (Mark Processed)
                mark_processed(voc_id, spell)
                success_count += 1
                print(f"  ✅ {spell} 处理成功")
            else:
                print(f"  ⚠️ {spell} 在 AI 返回中缺失")
                
        print(f"✨ 批次统计: 成功 {success_count}/{len(batch_words)}")

if __name__ == "__main__":
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        manager = StudyFlowManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n[Stop] 用户中止运行")
    except Exception as e:
        print(f"\n[Crash] 系统异常: {e}")
