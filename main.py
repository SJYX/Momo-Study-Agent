import os
import sys
import argparse
import runpy
from pathlib import Path

# ==============================================================================
# EARLY BOOTSTRAP: 用户配置热加载 (彻底消灭 subprocess 多进程套娃)
# ==============================================================================
# 必须在导入任何业务模块（尤其是 config）之前执行
if __name__ == "__main__":
    _user_from_env = bool(os.getenv("MOMO_USER"))
    if not _user_from_env and sys.stdin.isatty():
        import config
        # 如果当前是默认用户且处于交互模式，触发选择菜单
        if getattr(config, "ACTIVE_USER", "default") == "default":
            try:
                selected_user = config.pm.normalize_username(config.pm.pick_profile() or "")
                if not selected_user:
                    print("\n[Exit] 未选择有效用户，已退出。")
                    sys.exit(0)
                
                # 1. 直接在当前进程注入环境变量
                os.environ["MOMO_USER"] = selected_user
                
                # 2. 热重载 config 模块，使后续导包拿到真实用户配置
                import importlib
                importlib.reload(config)
            except (KeyboardInterrupt, EOFError):
                print("\n[Exit] 用户取消选择。")
                sys.exit(0)

# ==============================================================================
# 常规导包开始（此时 config 已经是最终用户的真实配置）
# ==============================================================================
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
    DATA_DIR,
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
# 进程锁机制：跨终端物理防多开 (防御 WalConflict 的最后防线)
# 从 web/backend/lock.py 导入共享实现
# ==============================================================================
from web.backend.lock import acquire_process_lock, release_process_lock


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
    """主逻辑管理类"""

    def __init__(self, environment=None, config_file=None):
        self.environment = environment or os.getenv("MOMO_ENV", "development")
        self.config_file = config_file or os.getenv("MOMO_CONFIG_FILE", "config/logging.yaml")

        get_full_config(self.environment, self.config_file)
        
        user = os.getenv("MOMO_USER") or ACTIVE_USER
        self.logger = setup_logger(user, environment=self.environment, config_file=self.config_file)
        self.session_id = str(uuid.uuid4())
        self.logger.set_context(session_id=self.session_id)

        self.momo = MaiMemoAPI(MOMO_TOKEN)
        self.ai_client = _build_ai_client()
        self.gemini = self.ai_client

        self.ui = CLIUIManager(self.logger)

        # 初始化并发写入/同步系统及数据库表
        init_concurrent_system()
        init_db()
        
        self.workflow = StudyWorkflow(
            logger=self.logger,
            ai_client=self.ai_client,
            momo_api=self.momo,
            ui_manager=self.ui,
        )

        # 启动时自动检查并入库未同步笔记
        unsynced = get_unsynced_notes()
        if unsynced:
            self.logger.info(f"发现 {len(unsynced)} 条待同步笔记，正在入队...")
            for note in unsynced:
                self.workflow.sync_manager.queue_maimemo_sync(
                    note["voc_id"],
                    note.get("spelling", ""),
                    clean_for_maimemo(note.get("basic_meanings", "")),
                    ["雅思"],
                    force_sync=True,
                )

    def run(self):
        while True:
            # 刷新任务数量
            self.logger.info("[菜单] 正在刷新任务状态...", module="main")
            today_items = []
            future_items = []
            try:
                today_res = self.momo.get_today_items(limit=500)
                today_items = (today_res or {}).get("data", {}).get("today_items", [])
                
                start_dt = datetime.now()
                end_dt = start_dt + timedelta(days=7)
                future_res = self.momo.query_study_records(
                    start_dt.strftime("%Y-%m-%dT00:00:00.000Z"),
                    end_dt.strftime("%Y-%m-%dT23:59:59.000Z"),
                )
                future_items = (future_res or {}).get("data", {}).get("records", [])
            except Exception as e:
                self.logger.warning(f"数据拉取失败: {e}", module="main")

            self.ui.render_main_menu(
                today_count=len(today_items),
                future_count=len(future_items),
                status_line=self.ui.consume_menu_status_line(),
            )
            choice = self.ui.wait_for_choice(["1", "2", "3", "4"])

            if choice == "1":
                self.workflow.process_word_list(today_items, "今日任务")
            elif choice == "2":
                days = self.ui.render_future_days_menu()
                if days > 0:
                    start_dt = datetime.now()
                    end_dt = start_dt + timedelta(days=days)
                    res = self.momo.query_study_records(
                        start_dt.strftime("%Y-%m-%dT00:00:00.000Z"),
                        end_dt.strftime("%Y-%m-%dT23:59:59.000Z"),
                    )
                    items = (res or {}).get("data", {}).get("records", [])
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
                    if records and self.ui.ask_confirmation(f"发现 {len(records)} 个单词，是否处理？"):
                        self.workflow.process_word_list(records, f"未来 {days} 天计划")
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
    # 【核心防御】在初始化任何数据库连接前获取进程锁
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


def web_main():
    """CLI 子命令入口：momo web ..."""
    project_root = Path(__file__).resolve().parent
    script_path = project_root / "scripts" / "start_web.py"
    runpy.run_path(str(script_path), run_name="__main__")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "web":
        # 支持：momo web [args...]
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        web_main()
        return

    parser = argparse.ArgumentParser(description="墨墨背单词AI助记系统")
    parser.add_argument(
        "--env",
        choices=["development", "staging", "production"],
        default=os.getenv("MOMO_ENV", "development"),
    )
    parser.add_argument("--config", default=os.getenv("MOMO_CONFIG_FILE", "config/logging.yaml"))
    args = parser.parse_args()

    # 执行主程序
    run(environment=args.env, config_file=args.config)


if __name__ == "__main__":
    main()
