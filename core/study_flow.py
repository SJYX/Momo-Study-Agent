"""core/study_flow.py: CLI 主流程业务编排类。

从 main.py 抽出，main.py 仅保留入口（EARLY BOOTSTRAP / argparse / acquire_process_lock）。

边界：
- 不持有进程锁（main.run() 负责 acquire_process_lock）
- 构造时初始化数据库 + 并发系统
- run() 是阻塞的菜单循环；shutdown() 幂等
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta

from config import ACTIVE_USER, MOMO_TOKEN
from core.factories import build_ai_client
from core.iteration_manager import IterationManager
from core.log_config import get_full_config
from core.logger import setup_logger
from core.maimemo_api import MaiMemoAPI
from core.study_workflow import StudyWorkflow
from core.sync_priority import Priority
from core.ui_manager import CLIUIManager
from database.connection import cleanup_concurrent_system, init_concurrent_system
from database.momo_words import get_unsynced_notes
from database.schema import init_db
from database.utils import clean_for_maimemo


class StudyFlowManager:
    """主逻辑管理类。"""

    def __init__(self, environment=None, config_file=None):
        self.environment = environment or os.getenv("MOMO_ENV", "development")
        self.config_file = config_file or os.getenv("MOMO_CONFIG_FILE", "config/logging.yaml")

        get_full_config(self.environment, self.config_file)

        user = os.getenv("MOMO_USER") or ACTIVE_USER
        self.logger = setup_logger(user, environment=self.environment, config_file=self.config_file)
        self.session_id = str(uuid.uuid4())
        self.logger.set_context(session_id=self.session_id)

        self.momo = MaiMemoAPI(MOMO_TOKEN)
        self.ai_client = build_ai_client()
        self.gemini = self.ai_client

        self.ui = CLIUIManager(self.logger)

        # 初始化数据库表 → 然后启动并发写入/同步系统
        # 必须先 init_db 建表，再启动守护线程（与 Web 端 user_context.py 顺序一致）
        init_db()
        init_concurrent_system()

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
                    priority=Priority.P1,
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
                    # 字段歧义由 process_word_list -> WordService.normalize_cloud_items 统一处理。
                    if items and self.ui.ask_confirmation(f"发现 {len(items)} 个单词，是否处理？"):
                        self.workflow.process_word_list(items, f"未来 {days} 天计划")
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


__all__ = ["StudyFlowManager"]
