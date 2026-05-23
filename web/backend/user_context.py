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
    # Phase 2: per-profile DB sync coordinator (event-driven, replaces global _sync_daemon)
    sync_coordinator: Any = None


class UserContextManager:
    """管理所有 profile 的 UserContext 实例（线程安全）。"""

    def __init__(self):
        self._contexts: Dict[str, UserContext] = {}
        self._lock = threading.Lock()
        # warmup 状态机:
        #   not_started → db_init_in_progress → db_init_done → done
        # db_init_in_progress 时, 该 profile 的 DB 还在建立 (pyturso bootstrap 可能要 80-141s)。
        # API 路由层应该在 db_init_in_progress 时返回 503 让前端等待。
        self._warmup_state: Dict[str, str] = {}
        self._first_warmup_done: Dict[str, bool] = {}
        self._init_locks: Dict[str, threading.Lock] = {}  # Profile 级别的初始化锁

    def get(self, profile_name: str) -> UserContext:
        """获取指定 profile 的 context，不存在则创建。"""
        # Fast path: read under lock.
        # 针对指定 profile 获取或创建独立的初始化锁，确保同一 profile 串行初始化
        with self._lock:
            if profile_name not in self._init_locks:
                self._init_locks[profile_name] = threading.Lock()
            profile_init_lock = self._init_locks[profile_name]

        with profile_init_lock:
            # 再次检查，防止在等待 profile_init_lock 期间已有其他线程完成初始化
            with self._lock:
                existing = self._contexts.get(profile_name)
            if existing is not None:
                return existing

            created = self._create_context(profile_name)

            with self._lock:
                # 最后的发布逻辑
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
            self._init_locks.pop(profile_name, None)
        if ctx:
            self._cleanup_context(ctx)

    def cleanup_all(self) -> None:
        """清理所有 profile 资源。"""
        with self._lock:
            contexts = list(self._contexts.values())
            self._contexts.clear()
            self._init_locks.clear()
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
            ai_client = MimoClient(
                api_key=cfg_snapshot.mimo_api_key,
                model_name=cfg_snapshot.mimo_model or None,
                api_base=cfg_snapshot.mimo_api_base or None,
            )
        else:
            from core.gemini_client import GeminiClient
            ai_client = GeminiClient(
                api_key=cfg_snapshot.gemini_api_key,
                model_name=cfg_snapshot.gemini_model or None,
            )

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

        # Phase 2: create per-profile sync coordinator (event-driven, replaces global polling)
        from database.sync_coordinator import ProfileSyncCoordinator, _registry_lock, _coordinators
        from database.backends import get_active_backend
        coordinator = ProfileSyncCoordinator(
            db_path=cfg_snapshot.db_path,
            backend=get_active_backend(),
        )
        abs_db_path = os.path.abspath(cfg_snapshot.db_path)
        with _registry_lock:
            _coordinators[abs_db_path] = coordinator

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
            sync_coordinator=coordinator,
        )

        # ⚠️ DB init (init_db + init_concurrent_system) 在后台线程跑——pyturso 首次
        # bootstrap 大库可能耗时 80-141s, 不能阻塞 _create_context 的调用方 (PUT
        # /api/users/active 等路由)。这之后调用方可以拿到 ctx, 但 DB 还没建好,
        # 由 is_db_ready() / /api/health/ready 告诉前端何时可以查询。
        # 笔记扫描 (_warmup_async) 紧跟在 DB init 之后,也在同一个后台线程里跑。
        self._warmup_sync_and_kick_async(ctx)

        return ctx

    def get_warmup_state(self, profile_name: str) -> str:
        """返回 profile 的 warmup 状态:
        'not_started' | 'db_init_in_progress' | 'db_init_done' | 'done'.
        """
        with self._lock:
            return self._warmup_state.get(profile_name, "not_started")

    def is_db_ready(self, profile_name: str) -> bool:
        """True 当且仅当该 profile 的 DB 已经 init 完毕、可以查询。

        前端/中间件应在调任何依赖 DB 的端点前检查此项, 否则返回 503。
        """
        return self.get_warmup_state(profile_name) in ("db_init_done", "done")

    def _warmup_sync_and_kick_async(self, ctx: UserContext) -> None:
        """启动 profile 的 warmup 后台线程 (DB init + 笔记扫描)。

        这个方法是非阻塞的 —— 仅设置状态标志并 fork 一个 daemon 线程。
        DB init 完毕后 is_db_ready() 转 True; 笔记扫描完毕后 state 转 'done'。
        """
        profile = (ctx.profile_name or "").strip().lower()
        with self._lock:
            state = self._warmup_state.get(profile, "not_started")
            if state in ("db_init_in_progress", "db_init_done", "done"):
                return
            self._warmup_state[profile] = "db_init_in_progress"

        thread = threading.Thread(
            target=self._warmup_chain_safe,
            args=(ctx, profile),
            name=f"warmup-{profile}",
            daemon=True,
        )
        thread.start()

    def _warmup_chain_safe(self, ctx: UserContext, profile: str) -> None:
        """后台线程入口: 先跑 DB init (慢, 80-141s), 再跑笔记扫描。"""
        # Phase 1: DB init —— 慢, pyturso 首次 bootstrap 可能 80-141s
        try:
            self._warmup_sync(ctx)
        except Exception as exc:
            try:
                ctx.logger.warning(
                    f"[Web] profile '{profile}' DB init 失败: {exc}",
                    module="user_context",
                )
            except Exception:
                pass
        finally:
            # 即使失败也要把状态推进, 否则前端永远等不到 ready
            # (业务路由仍可能在查询时报错,但起码不会无限 503)
            with self._lock:
                self._warmup_state[profile] = "db_init_done"

        # Phase 2: 笔记扫描 (best-effort, 失败不影响 ctx 可用性)
        try:
            self._warmup_async(ctx)
        except Exception as exc:
            try:
                ctx.logger.warning(
                    f"[Web] profile '{profile}' 异步 warmup 失败: {exc}",
                    module="user_context",
                )
            except Exception:
                pass
        finally:
            with self._lock:
                self._warmup_state[profile] = "done"

    def ensure_profile_ready(self, ctx: UserContext) -> None:
        """兼容入口: 启动后台 warmup 但立即返回 (不阻塞)。"""
        self._warmup_sync_and_kick_async(ctx)

    def _warmup_sync(self, ctx: UserContext) -> None:
        """阻塞段：DB schema 初始化 + 写连接单例 + 写并发系统启动。必须先于任何任务完成。"""
        from database.utils import _debug_log
        UserContextManager.prepare_for_task(ctx)
        from database.connection import init_concurrent_system
        from database.schema import init_db

        try:
            init_db(ctx.db_path)
        except Exception as e:
            _debug_log(f"[_warmup_sync] init_db 异常（已捕获，继续启动）: {e}", level="WARNING", module="web.user_context")

        init_concurrent_system()

    def _warmup_async(self, ctx: UserContext) -> None:
        """异步执行：把未同步笔记重新入队同步。"""
        from core.feature_flags import is_enabled
        from core.sync_priority import Priority
        from database.momo_words import get_unsynced_notes
        from database.utils import clean_for_maimemo

        # PLAYBOOK A4 Kill Switch：性能回退时 ops 可关闭自动 warmup 同步。
        # 注意 _warmup_sync（DB schema 初始化）始终运行，因为 ctx 必须可用。
        if not is_enabled("AUTO_WARMUP_SYNC_ENABLED", default=True):
            ctx.logger.warning(
                "[Web] AUTO_WARMUP_SYNC_ENABLED=False，跳过未同步笔记扫描与入队",
                module="user_context",
            )
            return

        # 异步线程也要确保 DB globals 指向正确的 profile，否则会拉错库
        UserContextManager.prepare_for_task(ctx)

        unsynced = get_unsynced_notes(db_path=ctx.db_path)
        if not unsynced:
            return

        profile = ctx.profile_name
        is_first = False
        with self._lock:
            if not self._first_warmup_done.get(profile, False):
                is_first = True
                self._first_warmup_done[profile] = True
        
        target_priority = Priority.P1 if is_first else Priority.P3

        ctx.logger.info(
            f"发现 {len(unsynced)} 条待同步笔记，正在后台入队 (Priority: {target_priority.name})...",
            module="user_context",
        )
        for note in unsynced:
            ctx.workflow.sync_manager.queue_maimemo_sync(
                note["voc_id"],
                note.get("spelling", ""),
                clean_for_maimemo(note.get("basic_meanings", "")),
                ["雅思"],
                force_sync=True,
                priority=target_priority,
                profile_name=ctx.profile_name,
            )

    @staticmethod
    def prepare_for_task(ctx: UserContext) -> None:
        """在执行数据库相关任务前，将 DB globals 切换到此 context。

        因为 database 模块使用模块级 DB_PATH 或直接读 config.DB_PATH，
        此方法确保任务执行期间读写的是正确的 profile 数据库。
        同时注入 profile 级 Turso 凭据到 os.environ 和模块级变量，
        因为 database/connection.py 的 _resolve_conn_context() 从 os.getenv() 读取。
        """
        try:
            import config as _cfg
            _cfg.DB_PATH = ctx.db_path
        except Exception:
            pass
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
        # 注入 profile 级 Turso 凭据到 os.environ + 模块级变量
        if ctx.turso_db_url:
            try:
                import os
                os.environ["TURSO_DB_URL"] = ctx.turso_db_url
                if ctx.turso_auth_token:
                    os.environ["TURSO_AUTH_TOKEN"] = ctx.turso_auth_token
                import database.connection as _db_conn2
                _db_conn2.set_runtime_cloud_credentials(
                    ctx.turso_db_url, ctx.turso_auth_token
                )
                import config as _cfg2
                _cfg2.TURSO_DB_URL = ctx.turso_db_url
                _cfg2.TURSO_AUTH_TOKEN = ctx.turso_auth_token
            except Exception:
                pass

    @staticmethod
    def _cleanup_context(ctx: UserContext) -> None:
        """释放单个 context 的资源。"""
        # Phase 2: shut down per-profile sync coordinator
        if ctx.sync_coordinator:
            try:
                ctx.sync_coordinator.shutdown()
            except Exception:
                pass
            try:
                from database.sync_coordinator import _registry_lock, _coordinators
                import os as _os
                abs_path = _os.path.abspath(ctx.db_path)
                with _registry_lock:
                    _coordinators.pop(abs_path, None)
            except Exception:
                pass
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
