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
import msvcrt

# 终端编码修正已移至 if __name__ == "__main__" 或入口函数中

class StudyFlowManager:
    """墨墨背单词 AI 助记主流程管理器。"""

    def __init__(self):
        # 初始化日志系统
        self.logger = setup_logger(ACTIVE_USER)
        self.momo = MaiMemoAPI(MOMO_TOKEN)
        
        init_db()  # 初始化主库

        # A. 展示运行信息
        self.logger.info(f"👤 [User] 当前用户: {ACTIVE_USER}")
        if AI_PROVIDER == "mimo":
            if not MIMO_API_KEY:
                raise ValueError("MIMO_API_KEY is required when using Mimo provider")
            self.ai_client = MimoClient(MIMO_API_KEY)
            self.logger.info(f"🤖 AI 模型: {AI_PROVIDER} (小米 Mimo)")
        else:
            if not GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY is required when using Gemini provider")
            self.ai_client = GeminiClient(GEMINI_API_KEY)
            self.logger.info(f"🤖 AI 模型: {AI_PROVIDER} (Google Gemini)")

    def _check_esc_interrupt(self):
        """检查是否按下 Esc 键中断程序。"""
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            if ord(ch) == 27:  # Esc
                print("\n" + "!"*30)
                self.logger.warning(" 检测到 Esc 键，正在紧急中断任务并保存进度...")
                print("!"*30)
                raise KeyboardInterrupt

    def _interruptible_sleep(self, seconds: float):
        """支持 Esc 中断的休眠。"""
        start_time = time.time()
        while time.time() - start_time < seconds:
            self._check_esc_interrupt()
            time.sleep(0.1)

    def _get_mode_selection(self) -> str:
        """支持 Esc 中断的模式选择界面。"""
        print("\n" + "-"*20)
        print("模式选择:")
        print("  1. [今日任务] 获取今天待学/待复习的单词 (默认)")
        print("  2. [未来计划] 预习未来几天“已在计划中”的复习任务")
        print("-" * 20)
        print("提示: 请输入选项 (1/2)，或按 [Esc] 直接退出程序")
        print("注: 模式 2 仅处理已加入背诵计划、且有预定复习日期的单词。")

        input_str = ""
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ord(ch) == 27:  # Esc
                    print("\n[Exit] 用户取消选择。")
                    sys.exit(0)
                elif ch == b'\r':  # Enter
                    print() 
                    break
                elif ch.isdigit():
                    digit = ch.decode('utf-8')
                    input_str += digit
                    print(digit, end='', flush=True)
                elif ord(ch) == 8: # Backspace
                    if input_str:
                        input_str = input_str[:-1]
                        print('\b \b', end='', flush=True)
        return input_str.strip() or "1"
        
    def run(self):
        """核心运行循环"""
        # A. 展示运行信息
        self.logger.info(f"👤 [User] 当前用户: {ACTIVE_USER}")
        if AI_PROVIDER == "mimo":
            self.logger.info(f"🤖 AI 模型: {AI_PROVIDER} (小米 Mimo)")
        else:
            self.logger.info(f"🤖 AI 模型: {AI_PROVIDER} (Google Gemini)")

        # B. 模式选择 (带 Esc 支持)
        mode = self._get_mode_selection()

        if mode == "2":
            days = input("请输入要预习的天数 (例如 3 或 7): ").strip()
            days = int(days) if days.isdigit() else 3
            start_dt = datetime.now()
            end_dt = start_dt + timedelta(days=days)
            start_date = start_dt.strftime("%Y-%m-%dT00:00:00.000Z")
            end_date = end_dt.strftime("%Y-%m-%dT23:59:59.000Z")
            
            self.logger.info(f"🚩 [未来模式] 预习接下来 {days} 天单词 ({start_dt.strftime('%m-%d')} ~ {end_dt.strftime('%m-%d')})...")
            res = self.momo.query_study_records(start_date, end_date)
            words = res.get("data", {}).get("records", []) if res else []
        else:
            self.logger.info("🚩 [今日模式] 获取今日待学单词...")
            res = self.momo.get_today_items(limit=500)
            words = res.get("data", {}).get("today_items", []) if res else []

        if not words:
            self.logger.info("📭 未发现待处理单词，流程结束。")
            return

        print("\n提示: 任务运行中可按住 [Esc] 键随时中断并保存。")
        self.logger.info(f"🚀 [Start] 启动学习流 (共计 {len(words)} 个单词, DRY_RUN={DRY_RUN})")
        
        # 2. 单词分流
        processed_in_this_run = []
        pending_words = []
        
        for w in words:
            self._check_esc_interrupt()
            voc_id = w.get("voc_id")
            spell = w.get("voc_spelling")
            
            # A. 检查当前用户副本
            if is_processed(voc_id):
                self.logger.info(f"  ⏭️ [Skipped] {spell} - 单词已存在于本地库")
                continue
            
            # B. 跨用户缓存检查 (Zero-Cost Cache)
            cache_res = find_word_in_community(voc_id)
            if cache_res:
                community_note, source_db = cache_res
                self.logger.info(f"  🏆 [Cache Hit] {spell} - 命中社区库 {source_db}")
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
                self._interruptible_sleep(sleep_time)

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
