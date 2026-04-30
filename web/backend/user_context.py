"""
web/backend/user_context.py: UserContextManager — profile 级资源隔离。

每个 profile 拥有独立的：
  logger / momo_api / ai_client / workflow / task_registry / logger_bridge

生命周期由 UserContextManager 统一管理。

P1 重构：不再修改全局 config.*，改用 config.switch_user() 初始化后快照配置到 context，
并通过 prepare_db_context() 在执行数据库操作前切 DB globals。
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
    turso_db_url: str = ""
    turso_auth_token: str = ""


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
        """为指定 profile 创建完整的运行时上下文。

        使用 config.switch_user() 初始化依赖（因为底层模块依赖全局变量），
        但初始化完成后快照配置到 context，并恢复原全局状态。
        """
        import config as cfg

        # 保存当前全局状态（初始化完成后恢复）
        saved = {
            "ACTIVE_USER": cfg.ACTIVE_USER,
            "MOMO_TOKEN": cfg.MOMO_TOKEN,
            "GEMINI_API_KEY": cfg.GEMINI_API_KEY,
            "MIMO_API_KEY": cfg.MIMO_API_KEY,
            "AI_PROVIDER": cfg.AI_PROVIDER,
            "DB_PATH": cfg.DB_PATH,
            "TEST_DB_PATH": cfg.TEST_DB_PATH,
            "TURSO_DB_URL": cfg.TURSO_DB_URL,
            "TURSO_AUTH_TOKEN": cfg.TURSO_AUTH_TOKEN,
        }

        try:
            # 切换到目标 profile 初始化所有依赖
            cfg.switch_user(profile_name)

            # 快照当前配置到 context
            import os
            from core.log_config import get_full_config
            from core.logger import setup_logger

            environment = os.getenv("MOMO_ENV", "development")
            config_file = os.getenv("MOMO_CONFIG_FILE", "config/logging.yaml")
            get_full_config(environment, config_file)

            logger = setup_logger(profile_name, environment=environment, config_file=config_file)
            session_id = str(uuid.uuid4())
            logger.set_context(session_id=session_id)

            from core.maimemo_api import MaiMemoAPI
            momo_api = MaiMemoAPI(cfg.MOMO_TOKEN)

            if cfg.AI_PROVIDER == "mimo":
                from core.mimo_client import MimoClient
                ai_client = MimoClient(cfg.MIMO_API_KEY)
            else:
                from core.gemini_client import GeminiClient
                ai_client = GeminiClient(cfg.GEMINI_API_KEY)

            # 初始化数据库（使用 switch_user 已设置的 DB globals）
            from database.connection import init_concurrent_system
            from database.schema import init_db
            init_concurrent_system()
            init_db()

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

            from web.backend.tasks import TaskRegistry
            from web.backend.logger_bridge import LoggerBridge

            task_registry = TaskRegistry()
            logger_bridge = LoggerBridge(task_registry)
            logger_bridge.attach(logger)

            logger.info(f"[Web] profile '{profile_name}' 上下文已初始化，AI: {cfg.AI_PROVIDER}", module="user_context")

            ctx = UserContext(
                profile_name=profile_name,
                logger=logger,
                momo_api=momo_api,
                ai_client=ai_client,
                workflow=workflow,
                task_registry=task_registry,
                logger_bridge=logger_bridge,
                db_path=cfg.DB_PATH,
                env_path=os.path.join(cfg.PROFILES_DIR, f"{profile_name}.env"),
                turso_db_url=cfg.TURSO_DB_URL or "",
                turso_auth_token=cfg.TURSO_AUTH_TOKEN or "",
            )

        finally:
            # 恢复原全局状态，避免污染其他 profile
            cfg.ACTIVE_USER = saved["ACTIVE_USER"]
            cfg.MOMO_TOKEN = saved["MOMO_TOKEN"]
            cfg.GEMINI_API_KEY = saved["GEMINI_API_KEY"]
            cfg.MIMO_API_KEY = saved["MIMO_API_KEY"]
            cfg.AI_PROVIDER = saved["AI_PROVIDER"]
            cfg.DB_PATH = saved["DB_PATH"]
            cfg.TEST_DB_PATH = saved["TEST_DB_PATH"]
            cfg.TURSO_DB_URL = saved["TURSO_DB_URL"]
            cfg.TURSO_AUTH_TOKEN = saved["TURSO_AUTH_TOKEN"]

            # 恢复 database 模块的 DB_PATH
            try:
                import database.connection as _db_conn
                _db_conn.DB_PATH = saved["DB_PATH"]
            except Exception:
                pass
            try:
                import database.momo_words as _db_momo
                _db_momo.DB_PATH = saved["DB_PATH"]
                _db_momo.TEST_DB_PATH = saved["TEST_DB_PATH"]
            except Exception:
                pass

        return ctx

    @staticmethod
    def prepare_for_task(ctx: UserContext) -> None:
        """在执行数据库相关任务前，将 DB globals 切换到此 context。

        因为 database 模块使用模块级 DB_PATH，此方法确保任务执行期间
        读写的是正确的 profile 数据库。
        """
        try:
            import database.connection as _db_conn
            _db_conn.DB_PATH = ctx.db_path
        except Exception:
            pass
        try:
            import database.momo_words as _db_momo
            _db_momo.DB_PATH = ctx.db_path
        except Exception:
            pass

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
