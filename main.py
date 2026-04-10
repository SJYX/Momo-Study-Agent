import sys
import io
import time
import uuid
import msvcrt
import os
import argparse
from datetime import datetime, timedelta
from config import (
    MOMO_TOKEN, GEMINI_API_KEY, MIMO_API_KEY, BATCH_SIZE, DRY_RUN,
    AI_PROVIDER, ACTIVE_USER, PROMPT_FILE, SCORE_PROMPT_FILE, REFINE_PROMPT_FILE
)
from core.maimemo_api import MaiMemoAPI
from core.gemini_client import GeminiClient
from core.mimo_client import MimoClient
from core.iteration_manager import IterationManager
from core.db_manager import (
    init_db, is_processed, mark_processed, get_processed_ids_in_batch,
    save_ai_word_note, save_ai_batch, clean_for_maimemo, find_word_in_community,
    get_file_hash, archive_prompt_file, log_progress_snapshots, sync_databases
)
from core.logger import setup_logger
from core.log_config import get_full_config
from core.log_archiver import auto_archive_logs

class StudyFlowManager:
    """墨墨背单词 AI 助记主流程管理器。"""

    def __init__(self, environment=None, config_file=None):
        # 获取环境配置
        self.environment = environment or os.getenv('MOMO_ENV', 'development')
        self.config_file = config_file or os.getenv('MOMO_CONFIG_FILE', 'config/logging.yaml')

        # 获取日志配置
        log_config = get_full_config(self.environment, self.config_file)

        # 设置日志器
        self.logger = setup_logger(
            ACTIVE_USER,
            environment=self.environment,
            config_file=self.config_file
        )

        # 设置会话ID
        session_id = str(uuid.uuid4())
        self.logger.set_context(session_id=session_id)

        self.logger.info(
            f"启动墨墨背单词AI助记系统",
            environment=self.environment,
            session_id=session_id,
            module="main",
            function="__init__"
        )

        self.momo = MaiMemoAPI(MOMO_TOKEN)
        init_db()

        # 如果启用了自动归档，执行一次归档
        if log_config.get("enable_compression", False):
            try:
                self.logger.info("执行自动日志归档", module="main", function="__init__")
                archived, removed = auto_archive_logs(
                    log_config["log_dir"],
                    log_config
                )
                self.logger.info(
                    f"自动归档完成: 归档{len(archived)}个文件, 清理{len(removed)}个文件",
                    archived_count=len(archived),
                    removed_count=len(removed),
                    module="main",
                    function="__init__"
                )
            except Exception as e:
                self.logger.warning(
                    f"自动归档失败: {e}",
                    error=str(e),
                    module="main",
                    function="__init__"
                )
        
        # 移除强制启动同步，改为主循环中互动式检查
        
        # A. 提示词多版本归档
        prompts = [
            (PROMPT_FILE, "main"),
            (SCORE_PROMPT_FILE, "score"),
            (REFINE_PROMPT_FILE, "refine")
        ]
        self.prompt_hashes = {}
        for p_path, p_type in prompts:
            h = get_file_hash(p_path)
            self.prompt_hashes[p_type] = h
            archive_prompt_file(p_path, h, p_type)
            self.logger.info(f"📝 [Prompt] {p_type.capitalize()} 版本: {h}", module="main", function="__init__")
        
        self.prompt_version = self.prompt_hashes["main"]

        # B. 初始化 AI 客户端
        if AI_PROVIDER == "mimo":
            if not MIMO_API_KEY: raise ValueError("MIMO_API_KEY required")
            self.ai_client = MimoClient(MIMO_API_KEY)
            self.logger.info(f"🤖 AI 模型: {AI_PROVIDER} (小米 Mimo)")
        else:
            if not GEMINI_API_KEY: raise ValueError("GEMINI_API_KEY required")
            self.ai_client = GeminiClient(GEMINI_API_KEY)
            self.logger.info(f"🤖 AI 模型: {AI_PROVIDER} (Google Gemini)")

    def _check_esc_interrupt(self):
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            if ord(ch) == 27:
                print("\n" + "!"*30)
                self.logger.warning(" 检测到 Esc 键，正在中断并保存...")
                print("!"*30)
                raise KeyboardInterrupt
            return ch
        return None

    def _wait_for_choice(self, valid_choices: list) -> str:
        """回归标准 input 以确保跨终端兼容性。"""
        while True:
            try:
                choice = input("请输入选项序号 (或按 Ctrl+C 退出): ").strip()
                if choice in valid_choices:
                    return choice
                print(f"❌ 无效选项，请从 {valid_choices} 中选择。")
            except (KeyboardInterrupt, EOFError):
                print("\n[Exit] 用户中断程序。")
                sys.exit(0)

    def run(self):
        # 启动时执行 Dry Run 检查一致性
        self.logger.info("正在检测云端数据同步状态...")
        stats = sync_databases(dry_run=True)
        un_up = stats.get('upload', 0)
        un_down = stats.get('download', 0)
        if un_up > 0 or un_down > 0:
            print(f"\n[!] 发现同步差异: 云端有 {un_down} 条新数据，本地有 {un_up} 条待上传。")
            ch = input("是否立即进行合并？(Y/N, 默认 Y): ").strip().lower()
            if ch != 'n':
                self.logger.info("🚩 正在同步数据库，请稍候...")
                sync_databases(dry_run=False)
                self.logger.info("✅ 数据同步完成。")
            else:
                self.logger.warning("用户选择跳过同步，可能导致本地运行基于旧数据。")

        while True:
            # 获取今日任务
            res_today = self.momo.get_today_items(limit=500)
            today_task = res_today.get("data", {}).get("today_items", []) if res_today else []
            
            # 获取预习计划
            start_dt = datetime.now()
            end_dt = start_dt + timedelta(days=7)
            res_future = self.momo.query_study_records(
                start_dt.strftime("%Y-%m-%dT00:00:00.000Z"), 
                end_dt.strftime("%Y-%m-%dT23:59:59.000Z")
            )
            future_task = res_future.get("data", {}).get("records", []) if res_future else []

            print("\n" + "="*35)
            print(f"👤 用户: {ACTIVE_USER} | 模式选择")
            print("="*35)
            print(f"  1. [今日任务] 处理今日待复习 ({len(today_task)} 个)")
            print(f"  2. [未来计划] 处理未来 7 天待学 ({len(future_task)} 个)")
            print(f"  3. [智能迭代] 优化薄弱词助记 (基于数据反馈)")
            print(f"  4. [同步&退出] 保存所有数据并安全退出")
            print("-" * 35)

            choice = self._wait_for_choice(["1", "2", "3", "4"])
            
            if choice == "1":
                self._process_word_list(today_task, "今日任务")
                self._trigger_post_run_sync()
            elif choice == "2":
                # 允许用户自定义预习天数
                print("\n" + "-"*35)
                try:
                    days_input = input("请输入预习天数 (建议 1-14 天, 直接回车默认为 7): ").strip()
                    if not days_input:
                        days = 7
                        selected_task = future_task # 复用初始获取的 7 天数据
                    else:
                        days = int(days_input)
                        if days <= 0: raise ValueError
                        self.logger.info(f"正在重新获取未来 {days} 天的任务...")
                        end_dt = start_dt + timedelta(days=days)
                        res_new = self.momo.query_study_records(
                            start_dt.strftime("%Y-%m-%dT00:00:00.000Z"), 
                            end_dt.strftime("%Y-%m-%dT23:59:59.000Z")
                        )
                        selected_task = res_new.get("data", {}).get("records", []) if res_new else []
                    
                    self.logger.info(f"已选取未来 {days} 天任务，共 {len(selected_task)} 个单词")
                    self._process_word_list(selected_task, f"未来 {days} 天计划")
                    self._trigger_post_run_sync()
                except ValueError:
                    print("❌ 输入无效，必须是正整数。回到主菜单。")
            elif choice == "3":
                im = IterationManager(self.ai_client, self.momo, self.logger)
                im.run_iteration(familiarity_threshold=3.0)
                self._trigger_post_run_sync()
            elif choice == "4":
                self.logger.info("正在执行最后的数据同步...")
                sync_databases(dry_run=False)
                self.logger.info("✅ 已安全保存所有数据至云端。再见！")
                break

    def _trigger_post_run_sync(self):
        """主流程结束后触发一次非阻塞或快捷的同步。"""
        self.logger.info("🔁 正在后台将最新进度推送到云端...", module="main")
        import threading
        t = threading.Thread(target=sync_databases, kwargs={'dry_run': False}, daemon=True)
        t.start()

    def _process_word_list(self, word_list, name):
        if not word_list:
            self.logger.info(f"{name} 列表为空。")
            return
            
        self.logger.info(f"正在启动 {name} 处理流程...")
        
        # 1. 记录进度快照 (Smart Snapshot)
        count = log_progress_snapshots(word_list)
        if count > 0:
            self.logger.info(f"📈 [Track] 已更新 {count} 个单词的进度流水")

        # 2. 批量过滤已处理单词 (减少云端往返)
        all_voc_ids = [w.get("voc_id") for w in word_list]
        processed_ids = get_processed_ids_in_batch(all_voc_ids)
        
        pending_words = []
        for w in word_list:
            self._check_esc_interrupt()
            voc_id = str(w.get("voc_id"))
            spell = w.get("voc_spelling")
            
            if voc_id in processed_ids:
                continue
            
            # 社区检查 (此操作由于涉及跨文件，暂维持单查，但因 processed 已过滤，频率已大幅降低)
            cache_res = find_word_in_community(voc_id)
            if cache_res:
                community_note, source_db = cache_res
                self.logger.info(f"  🏆 [Cache Hit] {spell} - {source_db}")
                save_ai_word_note(voc_id, community_note)
                if not DRY_RUN:
                    brief = clean_for_maimemo(community_note.get('basic_meanings', ''))
                    self.momo.sync_interpretation(voc_id, brief, tags=["社区缓存"])
                mark_processed(voc_id, spell)
                continue
                
            pending_words.append(w)
        
        if not pending_words:
            self.logger.info("✨ 无需调用 AI。")
            return
            
        self.logger.info(f"💎 [AI Phase] 需解析 {len(pending_words)} 个单词")
        
        for i in range(0, len(pending_words), BATCH_SIZE):
            batch = pending_words[i : i + BATCH_SIZE]
            batch_spells = [w["voc_spelling"] for w in batch]
            self.logger.info(f"批次 {i//BATCH_SIZE + 1} ({i+len(batch)}/{len(pending_words)})")
            
            start = time.time()
            results, metadata = self.ai_client.generate_mnemonics(batch_spells)
            latency = int((time.time() - start) * 1000)

            if not results:
                self.logger.error("AI 处理失败")
                continue
                
            bid = str(uuid.uuid4())
            save_ai_batch({
                "batch_id": bid, "request_id": metadata.get("request_id"),
                "ai_provider": AI_PROVIDER, "model_name": self.ai_client.model_name,
                "prompt_version": self.prompt_version, "batch_size": len(batch),
                "total_latency_ms": latency, "total_tokens": metadata.get("total_tokens", 0),
                "finish_reason": metadata.get("finish_reason")
            })
            self._process_results(batch, results, i, len(pending_words), bid)
            
            if i + BATCH_SIZE < len(pending_words):
                time.sleep(2 if BATCH_SIZE > 1 else 0.5)

    def _process_results(self, batch_words, ai_results, current_start, total, batch_id):
        ai_map = {item["spelling"].lower(): item for item in ai_results}
        
        # ⚠️ 不再使用跨 AI 调用的共享连接。
        # 原因：Turso/libsql 使用 Hrana 流式协议，流有服务端存活时限。
        # 在 AI API 调用期间（约 15+ 秒）持有同一流，会导致服务端回收流，
        # 后续 commit 时触发 "stream not found" 崩溃。
        # 改为让每个 DB 函数自行管理短生命周期连接，确保每次 write 都是新鲜流。
        for idx, w in enumerate(batch_words):
            num = current_start + idx + 1
            spell = w["voc_spelling"].lower()
            vid = str(w["voc_id"])
            
            if spell in ai_map:
                payload = ai_map[spell]
                meta = {
                    "batch_id": batch_id,
                    "original_meanings": w.get("voc_meanings"),
                    "maimemo_context": {
                        "review_count": w.get("review_count"),
                        "short_term_familiarity": w.get("short_term_familiarity")
                    }
                }
                # 写入 AI 笔记（函数内自管连接，流生命周期极短）
                save_ai_word_note(vid, payload, metadata=meta)
                
                sync_success = True
                if not DRY_RUN:
                    res = self.momo.list_interpretations(vid)
                    if not (res and res.get("success") and res.get("data", {}).get("interpretations", [])):
                        brief = clean_for_maimemo(payload.get('basic_meanings', ''))
                        self.logger.info(f"[{num}/{total}] ✅ {spell} 同步中...")
                        sync_success = self.momo.sync_interpretation(vid, brief, tags=["雅思"])
                
                # 只有同步成功（或跳过同步）才标记为已处理
                if sync_success:
                    mark_processed(vid, spell)
                else:
                    self.logger.error(f"❌ {spell} 同步至墨墨失败，流程将跳过标记以便下次重试")
            else:
                self.logger.warning(f"{spell} 结果缺失")

if __name__ == "__main__":
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='墨墨背单词AI助记系统')
    parser.add_argument('--env', '--environment',
                       choices=['development', 'staging', 'production'],
                       default=os.getenv('MOMO_ENV', 'development'),
                       help='运行环境 (默认: development)')
    parser.add_argument('--config', '--config-file',
                       default=os.getenv('MOMO_CONFIG_FILE', 'config/logging.yaml'),
                       help='配置文件路径 (默认: config/logging.yaml)')
    parser.add_argument('--log-level',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                       help='覆盖控制台日志级别')
    parser.add_argument('--async-log', action='store_true',
                       help='启用异步日志')
    parser.add_argument('--enable-stats', action='store_true',
                       help='启用日志统计')

    args = parser.parse_args()

    # 移除可能会导致 stdin 阻塞的强制编码重配置
    try:
        manager = StudyFlowManager(environment=args.env, config_file=args.config)

        # 如果指定了命令行参数，覆盖配置
        if args.log_level or args.async_log or args.enable_stats:
            # 重新创建日志器以应用覆盖配置
            log_config = get_full_config(args.env, args.config)
            if args.log_level:
                log_config["console_level"] = args.log_level
            if args.async_log:
                log_config["use_async"] = True
            if args.enable_stats:
                log_config["enable_stats"] = True

            manager.logger = setup_logger(
                ACTIVE_USER,
                environment=args.env,
                config_file=args.config,
                use_async=log_config.get("use_async"),
                enable_stats=log_config.get("enable_stats")
            )

        manager.run()
    except KeyboardInterrupt:
        # 尝试获取日志器，如果失败则使用print
        try:
            from core.logger import get_logger
            get_logger().info("用户手动退出")
        except:
            print("用户手动退出")
    except Exception as e:
        # 尝试获取日志器记录错误，如果失败则使用print
        try:
            from core.logger import get_logger
            get_logger().error(f"意外崩溃: {e}", exc_info=True)
        except Exception as log_error:
            print(f"程序崩溃: {e}")
            print(f"日志系统也出现错误: {log_error}")
    finally:
        print("\n程序已安全退出。")
