import argparse
import os
import signal
import uuid
from datetime import datetime, timedelta

from config import (
    ACTIVE_USER,
    AI_PROVIDER,
    BATCH_SIZE,
    DRY_RUN,
    GEMINI_API_KEY,
    MIMO_API_KEY,
    MOMO_TOKEN,
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

    # ──────────────────────────────────────────────────────────────────────────────
    # 交互式用户选择逻辑（从 config.py 移除后在此处补回）
    # ──────────────────────────────────────────────────────────────────────────────
    import sys
    from config import ACTIVE_USER, pm, _USER_FROM_ENV
    
    # 如果是交互式终端运行且没通过外部环境变量设定用户，则触发选择菜单
    if ACTIVE_USER == "default" and sys.stdin.isatty() and not _USER_FROM_ENV:
        try:
            selected_user = pm.normalize_username(pm.pick_profile() or "")
            if not selected_user:
                print("\n[Exit] 未选择有效用户，已退出，避免回退到 default。")
                sys.exit(0)

            os.environ["MOMO_USER"] = selected_user
            # 在 Windows 下 os.execv 会导致失去控制台输入流(stdin失效)
            # 使用 subprocess.run 并显式传递环境变量，确保子进程读取到最终用户
            import subprocess

            child_env = os.environ.copy()
            child_env["MOMO_USER"] = selected_user
            result = subprocess.run([sys.executable] + sys.argv, env=child_env)
            sys.exit(result.returncode)
        except (KeyboardInterrupt, EOFError):
            print("\n[Exit] 用户取消。")
            sys.exit(0)

    run(environment=args.env, config_file=args.config)
