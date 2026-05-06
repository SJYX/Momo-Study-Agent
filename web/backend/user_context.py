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
    # 运行时缓存 (key -> {data: any, ts: float})
    cache: Dict[str, Any] = field(default_factory=dict)


class UserContextManager:
    """管理所有 profile 的 UserContext 实例（线程安全）。"""

    def __init__(self):
        self._contexts: Dict[str, UserContext] = {}
        self._lock = threading.Lock()
        # warmup 三态：not_started → in_progress → done
        self._warmup_state: Dict[str, str] = {}

    def get(self, profile_name: str) -> UserContext:
        """获取指定 profile 的 context，不存在则创建。"""
        # Fast path: read under lock.
        with self._lock:
            existing = self._contexts.get(profile_name)
        if existing is not None:
            return existing

        # Slow path: initialize outside lock to avoid holding a global mutex
        # during potentially long I/O (db warmup, cloud auth, client init).
        created = self._create_context(profile_name)

        # Publish with double-check to handle races.
        with self._lock:
            existing = self._contexts.get(profile_name)
            if existing is not None:
                # Another thread already published a context.
                self._cleanup_context(created)
                return existing
            self._contexts[profile_name] = created
            return created

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

        P4-T4 后不再走 cfg.switch_user + finally 恢复全局态的老路径。改为：
          1. 用 ProfileConfig.load() 读出 profile env，得到不可变快照
          2. 用快照里的字段直接构造 logger / momo_api / ai_client / workflow
          3. prepare_for_task 在每个任务开始前把 db_path 切到当前 ctx
             （database.connection / database.momo_words 仍存模块级 DB_PATH，
             所以并发不同 profile 的任务时由 prepare_for_task 序列化）
        """
        import os
        from web.backend.profile_config import load_profile_config

        cfg_snapshot = load_profile_config(profile_name)

        from core.log_config import get_full_config
        from core.logger import setup_logger

        environment = os.getenv("MOMO_ENV", "development")
        config_file = os.getenv("MOMO_CONFIG_FILE", "config/logging.yaml")
        get_full_config(environment, config_file)

        logger = setup_logger(cfg_snapshot.profile_name, environment=environment, config_file=config_file)
        session_id = str(uuid.uuid4())
        logger.set_context(session_id=session_id)

        from core.maimemo_api import MaiMemoAPI
        momo_api = MaiMemoAPI(cfg_snapshot.momo_token)

        if cfg_snapshot.ai_provider == "mimo":
            from core.mimo_client import MimoClient
            ai_client = MimoClient(cfg_snapshot.mimo_api_key)
        else:
            from core.gemini_client import GeminiClient
            ai_client = GeminiClient(cfg_snapshot.gemini_api_key)

        from core.study_workflow import StudyWorkflow

        class _NullUI:
            def __getattr__(self, name):
                return lambda *a, **kw: None

        workflow = StudyWorkflow(
            logger=logger,
            ai_client=ai_client,
            momo_api=momo_api,
            ui_manager=_NullUI(),
            db_path=cfg_snapshot.db_path,
        )

        from web.backend.tasks import TaskRegistry
        from web.backend.logger_bridge import LoggerBridge

        task_registry = TaskRegistry()
        logger_bridge = LoggerBridge(task_registry)
        logger_bridge.attach(logger)

        logger.info(
            f"[Web] profile '{cfg_snapshot.profile_name}' 上下文已初始化，AI: {cfg_snapshot.ai_provider}",
            module="user_context",
        )

        ctx = UserContext(
            profile_name=cfg_snapshot.profile_name,
            logger=logger,
            momo_api=momo_api,
            ai_client=ai_client,
            workflow=workflow,
            task_registry=task_registry,
            logger_bridge=logger_bridge,
            db_path=cfg_snapshot.db_path,
            env_path=cfg_snapshot.env_path,
            turso_db_url=cfg_snapshot.turso_db_url,
            turso_auth_token=cfg_snapshot.turso_auth_token,
        )

        # warmup 仍然同步执行（T5 会异步化）
        self.ensure_profile_ready(ctx)

        return ctx

    def ensure_profile_ready(self, ctx: UserContext) -> None:
        """同步阶段必须完成才能让 context 投入使用；异步阶段（扫描待同步笔记并入队）
        在后台线程跑，不阻塞 Gateway 切换。"""
        profile = (ctx.profile_name or "").strip().lower()
        with self._lock:
            state = self._warmup_state.get(profile, "not_started")
            if state in ("done", "in_progress"):
                return
            self._warmup_state[profile] = "in_progress"

        try:
            self._warmup_sync(ctx)
        except Exception:
            with self._lock:
                # 失败时回滚状态，让下次 get(profile) 可以重试
                self._warmup_state[profile] = "not_started"
            raise

        # 启动后台异步部分（扫描 + 入队），不阻塞调用方
        thread = threading.Thread(
            target=self._warmup_async_safe,
            args=(ctx, profile),
            name=f"warmup-async-{profile}",
            daemon=True,
        )
        thread.start()

    def _warmup_sync(self, ctx: UserContext) -> None:
        """阻塞段：DB schema 初始化 + 写并发系统启动。必须先于任何任务完成。"""
        UserContextManager.prepare_for_task(ctx)
        from database.connection import init_concurrent_system
        from database.schema import init_db

        init_concurrent_system()
        init_db()

    def _warmup_async_safe(self, ctx: UserContext, profile: str) -> None:
        """异步段：扫描未同步笔记并入队。失败不影响 ctx 可用性。"""
        try:
            self._warmup_async(ctx)
            with self._lock:
                self._warmup_state[profile] = "done"
        except Exception as exc:
            with self._lock:
                # 部分完成也算 done — 这是 best-effort 后台扫描，不可阻塞下一次调用
                self._warmup_state[profile] = "done"
            try:
                ctx.logger.warning(
                    f"[Web] profile '{profile}' 异步 warmup 失败: {exc}",
                    module="user_context",
                )
            except Exception:
                pass

    def _warmup_async(self, ctx: UserContext) -> None:
        """异步执行：把未同步笔记重新入队同步。"""
        from database.momo_words import get_unsynced_notes
        from database.utils import clean_for_maimemo

        # 异步线程也要确保 DB globals 指向正确的 profile，否则会拉错库
        UserContextManager.prepare_for_task(ctx)

        unsynced = get_unsynced_notes(db_path=ctx.db_path)
        if not unsynced:
            return

        ctx.logger.info(
            f"发现 {len(unsynced)} 条待同步笔记，正在后台入队...",
            module="user_context",
        )
        for note in unsynced:
            ctx.workflow.sync_manager.queue_maimemo_sync(
                note["voc_id"],
                note.get("spelling", ""),
                clean_for_maimemo(note.get("basic_meanings", "")),
                ["雅思"],
                force_sync=True,
            )

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
