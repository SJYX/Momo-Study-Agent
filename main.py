import sys
import io
import time
from config import MOMO_TOKEN, GEMINI_API_KEY, MIMO_API_KEY, BATCH_SIZE, DRY_RUN, AI_PROVIDER, ACTIVE_USER
from core.maimemo_api import MaiMemoAPI
from core.gemini_client import GeminiClient
from core.mimo_client import MimoClient
from core.db_manager import (
    init_db, is_processed, mark_processed, 
    save_ai_word_note, clean_for_maimemo, find_word_in_community
)
from core.logger import setup_logger
from datetime import datetime, timedelta

# 终端编码修正已移至 if __name__ == "__main__" 或入口函数中

class StudyFlowManager:
    """墨墨背单词 AI 助记主流程管理器。"""

    def __init__(self):
        # 初始化日志系统
        self.logger = setup_logger(ACTIVE_USER)
        self.momo = MaiMemoAPI(MOMO_TOKEN)

        # 根据配置选择 AI 提供商
        self.logger.info(f"👤 [User] 当前用户: {ACTIVE_USER}")
        if AI_PROVIDER == "mimo":
            if not MIMO_API_KEY:
                raise ValueError("MIMO_API_KEY is required when using Mimo provider")
            self.ai_client = MimoClient(MIMO_API_KEY)
            self.logger.info(f"🤖 使用小米 Mimo 模型: {self.ai_client.model_name}")
        else:
            if not GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY is required when using Gemini provider")
            self.ai_client = GeminiClient(GEMINI_API_KEY)
            self.logger.info(f"🤖 使用 Google Gemini 模型: {self.ai_client.model_name}")

        init_db()  # 初始化主库
        
    def run(self):
        """核心运行循环"""
        # 1. 模式选择
        print("\n" + "-"*20)
        print("模式选择:")
        print("  1. [今日任务] 获取今天待学/待复习的单词 (默认)")
        print("  2. [未来预习] 预习接下来几天的单词")
        mode_input = input("请输入选项 (1/2): ").strip()

        if mode_input == "2":
            days = input("请输入要预习的天数 (例如 3 或 7): ").strip()
            days = int(days) if days.isdigit() else 3
            
            # 计算日期范围 (北京时间)
            start_dt = datetime.now()
            end_dt = start_dt + timedelta(days=days)
            # 格式化为 ISO 格式
            start_date = start_dt.strftime("%Y-%m-%dT00:00:00.000Z")
            end_date = end_dt.strftime("%Y-%m-%dT23:59:59.000Z")
            
            self.logger.info(f"🚩 [未来模式] 正在获取接下来的 {days} 天单词 ({start_dt.strftime('%m-%d')} ~ {end_dt.strftime('%m-%d')})...")
            res = self.momo.query_study_records(start_date, end_date)
            words = res.get("data", {}).get("records", []) if res else []
        else:
            self.logger.info("🚩 [今日模式] 正在获取今日待学单词...")
            res = self.momo.get_today_items(limit=500)
            words = res.get("data", {}).get("today_items", []) if res else []

        if not words:
            self.logger.info("📭 未发现待处理单词，流程结束。")
            return

        self.logger.info(f"🚀 [Start] 启动学习流 (共计 {len(words)} 个单词, DRY_RUN={DRY_RUN})")
        
        # 2. 单词分流
        processed_in_this_run = []
        pending_words = []
        
        for w in words:
            voc_id = w.get("voc_id")
            spell = w.get("voc_spelling")
            
            # A. 检查当前用户副本
            if is_processed(voc_id):
                continue
            
            # B. 跨用户缓存检查 (Zero-Cost Cache)
            community_note = find_word_in_community(voc_id)
            if community_note:
                self.logger.info(f"  🏆 [Cache Hit] 发现社区贡献记录: {spell}")
                # 迁移数据：保存到当前库 + 同步到墨墨 + 标记处理
                save_ai_word_note(voc_id, community_note)
                if not DRY_RUN:
                    brief_note = clean_for_maimemo(community_note.get('basic_meanings', ''))
                    self.momo.sync_interpretation(voc_id, brief_note, tags=["社区缓存", "雅思"])
                mark_processed(voc_id, spell)
                continue
                
            # C. 确实需要 AI 解析
            pending_words.append(w)
        
        if not pending_words:
            self.logger.info("✨ 所有单词均已通过缓存或本地记录处理，无需调用 AI。")
            return
            
        self.logger.info(f"💎 [AI Phase] 共有 {len(pending_words)} 个单词需要调用 AI 模型解析")
        
        # 3. 按 BATCH_SIZE 进行批处理
        for i in range(0, len(pending_words), BATCH_SIZE):
            batch = pending_words[i : i + BATCH_SIZE]
            batch_spellings = [w["voc_spelling"] for w in batch]
            
            self.logger.info(f"正在处理批次 {i//BATCH_SIZE + 1} (进度: {i+len(batch)}/{len(pending_words)})...")
            
            # AI 生成
            ai_results = self.ai_client.generate_mnemonics(batch_spellings)
            if not ai_results:
                self.logger.error(f"批次 {i//BATCH_SIZE + 1} AI 调用失败。")
                continue
                
            # 4. 结果对照并保存
            self._process_results(batch, ai_results, current_start=i, total=len(pending_words))
            
            # 频率控制
            if i + BATCH_SIZE < len(pending_words):
                sleep_time = 0.5 if BATCH_SIZE == 1 else 2
                self.logger.info(f"⏳ 缓冲 {sleep_time:.1f} 秒...")
                time.sleep(sleep_time)

    def _process_results(self, batch_words, ai_results, current_start, total):
        """将 AI 结果映射回原始单词并持久化。"""
        # 转为字典加速查找
        ai_dict = {item["spelling"].lower(): item for item in ai_results}
        
        success_count = 0
        for idx, w in enumerate(batch_words):
            current_num = current_start + idx + 1
            spell = w["voc_spelling"].lower()
            voc_id = w["voc_id"]
            
            if spell in ai_dict:
                payload = ai_dict[spell]
                
                # A. 写入本地库 (DB Isolation)
                save_ai_word_note(voc_id, payload)
                
                # B. 同步至墨墨 (Sync to Maimemo)
                if not DRY_RUN:
                    # 获取已有释义信息
                    res_intp = self.momo.list_interpretations(voc_id)
                    has_intp = False
                    if res_intp and res_intp.get("success"):
                        intps = res_intp.get("data", {}).get("interpretations", [])
                        if intps:
                            has_intp = True
                            
                    if has_intp:
                        self.logger.info(f"[{current_num}/{total}] [Protect] {spell} 在墨墨中已存在释义，跳过推送")
                    else:
                        brief_note = clean_for_maimemo(payload.get('basic_meanings', ''))
                        self.momo.sync_interpretation(voc_id, brief_note, tags=["雅思"])
                        self.logger.info(f"[{current_num}/{total}] ✅ {spell} 释义已同步")
                
                # C. 标记已处理 (Mark Processed)
                mark_processed(voc_id, spell)
                success_count += 1
            else:
                self.logger.warning(f"[{current_num}/{total}] ⚠️ {spell} 在 AI 返回中缺失")
                
        self.logger.info(f"✨ 批次统计: 成功 {success_count}/{len(batch_words)}")

if __name__ == "__main__":
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        manager = StudyFlowManager()
        manager.run()
    except KeyboardInterrupt:
        # 获取 logger 手动记录，因为 manager 可能没初始化完
        from core.logger import get_logger
        get_logger().info("用户中止运行")
    except Exception as e:
        from core.logger import get_logger
        get_logger().error(f"系统异常: {e}", exc_info=True)
    finally:
        print("\n" + "="*30)
        try:
            import msvcrt
            print("任务处理完毕。请按 [Esc] 键退出程序...")
            while True:
                if msvcrt.kbhit():
                    char = msvcrt.getch()
                    if ord(char) == 27:  # 27 is the ASCII code for Esc
                        break
        except ImportError:
            # 非 Windows 环境或导入失败时的兜底方案
            input("任务处理完毕。按 [回车键] 退出程序...")
