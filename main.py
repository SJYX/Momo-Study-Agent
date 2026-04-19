import os
import sys

# ==============================================================================
# EARLY BOOTSTRAP: 用户配置热加载 (彻底消灭 subprocess 多进程套娃)
# ==============================================================================
# 确保这段代码在所有的 from config import ... 之前执行！
if __name__ == "__main__":
    _user_from_env = bool(os.getenv("MOMO_USER"))
    if not _user_from_env and sys.stdin.isatty():
        import config
        if getattr(config, "ACTIVE_USER", "default") == "default":
            selected_user = config.pm.normalize_username(config.pm.pick_profile() or "")
            if not selected_user:
                print("\n[Exit] 未选择有效用户，已退出，避免回退到 default。")
                sys.exit(0)
            
            # 1. 注入环境变量到当前进程
            os.environ["MOMO_USER"] = selected_user
            
            # 2. 热重载 config 模块，刷新所有常量（当前进程继续执行，无需开启子进程！）
            import importlib
            importlib.reload(config)

# ==============================================================================
# 常规导包开始（此时 config 已经是最终用户的真实配置）
# ==============================================================================
import argparse
import signal
import uuid
import atexit
from datetime import datetime, timedelta

from config import (
    ACTIVE_USER,
    AI_PROVIDER,
    BATCH_SIZE,
    DRY_RUN,
    GEMINI_API_KEY,
    MIMO_API_KEY,
    MOMO_TOKEN,
    DATA_DIR,  # 引入 DATA_DIR 用于存放进程锁
)
from database.connection import cleanup_concurrent_system, init_concurrent_system
from database.momo_words import (
    get_local_word_note,
    get_processed_ids_in_batch,
    get_unsynced_notes,
    is_processed,
    log_progress_snapshots,
    mark_processed,
    save_ai_batch,
    save_ai_word_note,
)
from database.schema import init_db
from database.utils import clean_for_maimemo
from core.iteration_manager import IterationManager
from core.log_config import get_full_config
from core.logger import setup_logger
from core.maimemo_api import MaiMemoAPI
from core.mimo_client import MimoClient
from core.study_workflow import StudyWorkflow
from core.ui_manager import CLIUIManager

# ==============================================================================
# 进程锁机制：防御多终端/脚本同时拉起争抢数据库
# ==============================================================================
_process_lock_fd = None

def acquire_process_lock():
    global _process_lock_fd
    lock_file = os.path.join(DATA_DIR, ".process.lock")
    os.makedirs(DATA_DIR, exist_ok=True)
    
    try:
        if os.name == 'nt':  # Windows 系统底层锁
            import msvcrt
            _process_lock_fd = os.open(lock_file, os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            msvcrt.locking(_process_lock_fd, msvcrt.LK_NBLCK, 1)
        else:  # Unix/Linux/Mac 系统底层锁
            import fcntl
            _process_lock_fd = os.open(lock_file, os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            fcntl.flock(_process_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        print(f"\n❌ [致命错误] 检测到程序已经在运行中！\n为保护数据库防冲突(WalConflict)，已拦截本次启动。\n如确信无其他进程在运行，请手动删除锁文件后重试: {lock_file}\n")
        sys.exit(1)
        
    def release_process_lock():
        global _process_lock_fd
        if _process_lock_fd is not None:
            try:
                if os.name == 'nt':
                    import msvcrt
                    os.lseek(_process_lock_fd, 0, os.SEEK_SET)
                    msvcrt.locking(_process_lock_fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(_process_lock_fd, fcntl.LOCK_UN)
                os.close(_process_lock_fd)
                if os.path.exists(lock_file):
                    os.remove(lock_file)
            except Exception:
                pass
            _process_lock_fd = None

    atexit.register(release_process_lock)


def _build_ai_client():
    if AI_PROVIDER == "mimo":
        if not MIMO_API_KEY:
            raise ValueError("MIMO_API_KEY required")
        return MimoClient(MIMO_API_KEY)
    from core.gemini_client import GeminiClient

    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY required")
    return GeminiClient(GEMINI_API_KEY)


class StudyFlowManager:
    """Backward-compatible facade that delegates work to modular managers."""

    def __init__(self, environment=None, config_file=None):
        self.environment = environment or os.getenv("MOMO_ENV", "development")
        self.config_file = config_file or os.getenv("MOMO_CONFIG_FILE", "config/logging.yaml")

        get_full_config(self.environment, self.config_file)
        # 使用最终确认的用户名初始化日志
        user = os.getenv("MOMO_USER") or ACTIVE_USER
        self.logger = setup_logger(user, environment=self.environment, config_file=self.config_file)
        self.session_id = str(uuid.uuid4())
        self.logger.set_context(session_id=self.session_id)

        self.momo = MaiMemoAPI(MOMO_TOKEN)
        self.ai_client = _build_ai_client()
        # Legacy alias retained for tests/scripts that still use manager.gemini.
        self.gemini = self.ai_client

        self.ui = CLIUIManager(self.logger)

        init_concurrent_system()
        init_db()
        self.workflow = StudyWorkflow(
            logger=self.logger,
            ai_client=self.ai_client,
            momo_api=self.momo,
            ui_manager=self.ui,
        )

        unsynced = get_unsynced_notes()
        for note in unsynced:
            self.workflow.sync_manager.queue_maimemo_sync(
                note["voc_id"],
                note.get("spelling", ""),
                clean_for_maimemo(note.get("basic_meanings", "")),
                ["雅思"],
                force_sync=True,
            )

    def _wait_for_choice(self, valid_choices):
        return self.ui.wait_for_choice(valid_choices)

    def run(self):
        while True:
            # 每轮菜单前动态拉取今日/未来任务数量，避免界面固定显示 0。
            self.logger.info("[菜单] 正在刷新今日/未来任务数量...", module="main")
            today_items = []
            future_items = []
            try:
                today_res = self.momo.get_today_items(limit=500)
                today_items = (today_res or {}).get("data", {}).get("today_items", [])
            except Exception as e:
                self.logger.warning(f"今日任务拉取失败: {e}", module="main")

            try:
                start_dt = datetime.now()
                end_dt = start_dt + timedelta(days=7)
                future_res = self.momo.query_study_records(
                    start_dt.strftime("%Y-%m-%dT00:00:00.000Z"),
                    end_dt.strftime("%Y-%m-%dT23:59:59.000Z"),
                )
                future_items = (future_res or {}).get("data", {}).get("records", [])
            except Exception as e:
                self.logger.warning(f"未来任务拉取失败: {e}", module="main")

            self.logger.info(
                f"[菜单] 刷新完成：今日 {len(today_items)}，未来 {len(future_items)}",
                module="main",
            )

            self.ui.render_main_menu(
                today_count=len(today_items),
                future_count=len(future_items),
                status_line=self.ui.consume_menu_status_line(),
            )
            choice = self._wait_for_choice(["1", "2", "3", "4"])

            if choice == "1":
                self.workflow.process_word_list(today_items, "今日任务")
            elif choice == "2":
                # 未来计划：子菜单选择天数
                days_to_query = self.ui.render_future_days_menu()
                if days_to_query <= 0:
                    continue
                
                self.logger.info(f"[菜单] 正在请求未来 {days_to_query} 天的任务...", module="main")
                try:
                    start_dt = datetime.now()
                    end_dt = start_dt + timedelta(days=days_to_query)
                    res = self.momo.query_study_records(
                        start_dt.strftime("%Y-%m-%dT00:00:00.000Z"),
                        end_dt.strftime("%Y-%m-%dT23:59:59.000Z"),
                    )
                    items = (res or {}).get("data", {}).get("records", [])
                    
                    if not items:
                        self.ui.ui_print(f"💡 未来 {days_to_query} 天内没有发现待处理任务。")
                        continue
                        
                    # 转换映射
                    records = []
                    for it in items:
                        spell = it.get("voc_spelling") or it.get("spelling")
                        vid = it.get("voc_id") or it.get("id")
                        if spell and vid:
                            records.append({
                                "voc_id": vid,
                                "voc_spelling": spell,
                                "voc_meanings": it.get("voc_meanings") or it.get("meanings") or ""
                            })
                    
                    if not records:
                        self.ui.ui_print("💡 未能解析到有效的单词信息。")
                        continue

                    if self.ui.ask_confirmation(f"发现未来 {days_to_query} 天共有 {len(records)} 个单词，是否开始处理？"):
                        self.workflow.process_word_list(records, f"未来 {days_to_query} 天计划")
                    else:
                        self.logger.info("用户取消了未来计划处理", module="main")

                except Exception as e:
                    self.logger.error(f"未来任务拉取失败: {e}", module="main")
            elif choice == "3":
                manager = IterationManager(ai_client=self.ai_client, momo_api=self.momo, logger=self.logger)
                manager.run_iteration()
            else:
                break

    def shutdown(self):
        try:
            if getattr(self, "workflow", None):
                self.workflow.shutdown()
            if hasattr(self.momo, "close"):
                self.momo.close()
            if hasattr(self.ai_client, "close"):
                self.ai_client.close()
        finally:
            cleanup_concurrent_system()


def run(environment=None, config_file=None):
    # 【最核心防御】在初始化数据库前，夺取进程锁！
    acquire_process_lock()
    
    manager = None
    try:
        manager = StudyFlowManager(environment=environment, config_file=config_file)
        manager.run()
    except KeyboardInterrupt:
        if manager and getattr(manager, "logger", None):
            manager.logger.info("用户手动退出", module="main")
    except Exception as e:
        if manager and getattr(manager, "logger", None):
            manager.logger.error(f"意外崩溃: {e}", exc_info=True, module="main")
        raise
    finally:
        if manager:
            manager.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="墨墨背单词AI助记系统（模块化入口）")
    parser.add_argument(
        "--env",
        "--environment",
        choices=["development", "staging", "production"],
        default=os.getenv("MOMO_ENV", "development"),
    )
    parser.add_argument("--config", "--config-file", default=os.getenv("MOMO_CONFIG_FILE", "config/logging.yaml"))
    args = parser.parse_args()

    # 之前位于此处的 subprocess.run(父子进程套娃) 逻辑已被移除，由文件顶部的 EARLY BOOTSTRAP 完美替代
    run(environment=args.env, config_file=args.config)