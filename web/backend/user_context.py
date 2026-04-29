"""
web/backend/user_context.py: UserContextManager — profile 级资源隔离。

每个 profile 拥有独立的：
  logger / momo_api / ai_client / workflow / task_registry / logger_bridge

生命周期由 UserContextManager 统一管理。
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class UserContext:
    """单个 profile 的运行时上下文。"""
    profile_name: str
    logger: Any = None
    momo_api: Any = None
    ai_client: Any = None
    workflow: Any = None
    task_registry: Any = None
    logger_bridge: Any = None
    db_path: str = ""
    env_path: str = ""


class UserContextManager:
    """管理所有 profile 的 UserContext 实例（线程安全）。"""

    def __init__(self):
        self._contexts: Dict[str, UserContext] = {}
        self._lock = threading.Lock()

    def get(self, profile_name: str) -> UserContext:
        """获取指定 profile 的 context，不存在则创建。"""
        with self._lock:
            ctx = self._contexts.get(profile_name)
            if ctx is None:
                ctx = self._create_context(profile_name)
                self._contexts[profile_name] = ctx
            return ctx

    def has(self, profile_name: str) -> bool:
        with self._lock:
            return profile_name in self._contexts

    def list_profiles(self) -> list[str]:
        with self._lock:
            return list(self._contexts.keys())

    def cleanup(self, profile_name: str) -> None:
        """清理指定 profile 的资源。"""
        with self._lock:
            ctx = self._contexts.pop(profile_name, None)
        if ctx:
            self._cleanup_context(ctx)

    def cleanup_all(self) -> None:
        """清理所有 profile 资源。"""
        with self._lock:
            contexts = list(self._contexts.values())
            self._contexts.clear()
        for ctx in contexts:
            self._cleanup_context(ctx)

    def _create_context(self, profile_name: str) -> UserContext:
        """为指定 profile 创建完整的运行时上下文。"""
        # 1. 切换 config 到目标 profile
        import config as cfg
        cfg.switch_user(profile_name)

        # 2. 初始化 logger
        import os
        from core.log_config import get_full_config
        from core.logger import setup_logger

        environment = os.getenv("MOMO_ENV", "development")
        config_file = os.getenv("MOMO_CONFIG_FILE", "config/logging.yaml")
        get_full_config(environment, config_file)

        logger = setup_logger(profile_name, environment=environment, config_file=config_file)
        session_id = str(uuid.uuid4())
        logger.set_context(session_id=session_id)

        # 3. 初始化墨墨 API
        from core.maimemo_api import MaiMemoAPI
        momo_api = MaiMemoAPI(cfg.MOMO_TOKEN)

        # 4. 初始化 AI 客户端
        if cfg.AI_PROVIDER == "mimo":
            from core.mimo_client import MimoClient
            ai_client = MimoClient(cfg.MIMO_API_KEY)
        else:
            from core.gemini_client import GeminiClient
            ai_client = GeminiClient(cfg.GEMINI_API_KEY)

        # 5. 初始化数据库
        from database.connection import init_concurrent_system
        from database.schema import init_db
        init_concurrent_system()
        init_db()

        # 6. 初始化 workflow
        from core.study_workflow import StudyWorkflow
        from database.momo_words import get_unsynced_notes
        from database.utils import clean_for_maimemo

        class _NullUI:
            def __getattr__(self, name):
                return lambda *a, **kw: None

        workflow = StudyWorkflow(
            logger=logger,
            ai_client=ai_client,
            momo_api=momo_api,
            ui_manager=_NullUI(),
        )

        # 7. 入队未同步笔记
        unsynced = get_unsynced_notes()
        if unsynced:
            logger.info(f"发现 {len(unsynced)} 条待同步笔记，正在入队...", module="user_context")
            for note in unsynced:
                workflow.sync_manager.queue_maimemo_sync(
                    note["voc_id"],
                    note.get("spelling", ""),
                    clean_for_maimemo(note.get("basic_meanings", "")),
                    ["雅思"],
                    force_sync=True,
                )

        # 8. TaskRegistry + LoggerBridge
        from web.backend.tasks import TaskRegistry
        from web.backend.logger_bridge import LoggerBridge

        task_registry = TaskRegistry()
        logger_bridge = LoggerBridge(task_registry)
        logger_bridge.attach(logger)

        logger.info(f"[Web] profile '{profile_name}' 上下文已初始化，AI: {cfg.AI_PROVIDER}", module="user_context")

        return UserContext(
            profile_name=profile_name,
            logger=logger,
            momo_api=momo_api,
            ai_client=ai_client,
            workflow=workflow,
            task_registry=task_registry,
            logger_bridge=logger_bridge,
            db_path=cfg.DB_PATH,
            env_path=os.path.join(cfg.PROFILES_DIR, f"{profile_name}.env"),
        )

    @staticmethod
    def _cleanup_context(ctx: UserContext) -> None:
        """释放单个 context 的资源。"""
        if ctx.logger_bridge and ctx.logger:
            try:
                ctx.logger_bridge.detach(ctx.logger)
            except Exception:
                pass
        if ctx.workflow:
            try:
                ctx.workflow.shutdown()
            except Exception:
                pass
        if ctx.momo_api and hasattr(ctx.momo_api, "close"):
            try:
                ctx.momo_api.close()
            except Exception:
                pass
        if ctx.ai_client and hasattr(ctx.ai_client, "close"):
            try:
                ctx.ai_client.close()
            except Exception:
                pass
        if ctx.task_registry:
            try:
                ctx.task_registry.shutdown()
            except Exception:
                pass
