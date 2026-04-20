import os
import sys
import argparse
import importlib

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
    DB_PATH,
    HUB_DB_PATH,
    TURSO_DB_URL,
    TURSO_DB_HOSTNAME,
    TURSO_AUTH_TOKEN,
)
from database import connection as db_connection
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
from database import schema as db_schema
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
# ==============================================================================
_process_lock_fd = None

def acquire_process_lock():
    """获取文件排他锁，确保系统内只有一个进程在操作数据库"""
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
        print(f"\n❌ [致命错误] 检测到程序已经在运行中！")
        print(f"为保护数据库防冲突(WalConflict)，已拦截本次启动。")
        print(f"如确信无其他进程运行，请手动删除锁文件: {lock_file}\n")
        sys.exit(1)
        
    def release_process_lock():
        """释放锁文件"""
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

    # 注册退出钩子，确保进程死亡时释放锁
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
    """主逻辑管理类"""

    def __init__(self, environment=None, config_file=None):
        self.environment = environment or os.getenv("MOMO_ENV", "development")
        self.config_file = config_file or os.getenv("MOMO_CONFIG_FILE", "config/logging.yaml")

        get_full_config(self.environment, self.config_file)
        
        user = os.getenv("MOMO_USER") or ACTIVE_USER
        self.logger = setup_logger(user, environment=self.environment, config_file=self.config_file)
        self.session_id = str(uuid.uuid4())
        self.logger.set_context(session_id=self.session_id)

        # 将最终用户配置显式同步到 database 运行态，避免落到 default 库
        db_connection.set_runtime_db_paths(DB_PATH, HUB_DB_PATH)
        db_connection.set_runtime_cloud_credentials(
            TURSO_DB_URL,
            TURSO_AUTH_TOKEN,
            TURSO_DB_HOSTNAME,
        )
        db_schema.set_runtime_db_path(DB_PATH)

        active_user = os.getenv("MOMO_USER") or ACTIVE_USER
        cloud_host = TURSO_DB_HOSTNAME or (TURSO_DB_URL or "")
        cloud_host = str(cloud_host).replace("https://", "").replace("libsql://", "")
        cloud_db_name = ""
        if cloud_host:
            cloud_db_name = cloud_host.split(".", 1)[0]
        self.logger.info(
            f"[Boot] active_user={active_user}, db_path={DB_PATH}, "
            f"cloud_host={cloud_host or 'local-only'}, cloud_db_name={cloud_db_name or 'n/a'}",
            module="main",
        )

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
            self.logger.debug("[菜单] 正在刷新任务状态...", module="main")
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
            try:
                manager.logger.info("用户手动退出", module="main")
            except KeyboardInterrupt:
                pass
            except Exception:
                pass
    except Exception as e:
        if manager and getattr(manager, "logger", None):
            manager.logger.error(f"意外崩溃: {e}", exc_info=True, module="main")
        raise
    finally:
        if manager:
            manager.shutdown()


if __name__ == "__main__":
    # 确保 main.py 早期用户选择后，所有模块拿到同一份最终 config。
    import config as _runtime_config
    _runtime_config = importlib.reload(_runtime_config)
    globals()["ACTIVE_USER"] = _runtime_config.ACTIVE_USER
    globals()["DB_PATH"] = _runtime_config.DB_PATH
    globals()["HUB_DB_PATH"] = _runtime_config.HUB_DB_PATH
    globals()["TURSO_DB_URL"] = _runtime_config.TURSO_DB_URL
    globals()["TURSO_DB_HOSTNAME"] = _runtime_config.TURSO_DB_HOSTNAME
    globals()["TURSO_AUTH_TOKEN"] = _runtime_config.TURSO_AUTH_TOKEN
    db_connection.set_runtime_db_paths(_runtime_config.DB_PATH, _runtime_config.HUB_DB_PATH)
    db_connection.set_runtime_cloud_credentials(
        _runtime_config.TURSO_DB_URL,
        _runtime_config.TURSO_AUTH_TOKEN,
        _runtime_config.TURSO_DB_HOSTNAME,
    )
    db_schema.set_runtime_db_path(_runtime_config.DB_PATH)

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
