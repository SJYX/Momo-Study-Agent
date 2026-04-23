"""
web/backend/app.py: FastAPI 工厂 — lifespan 初始化/清理 + 路由注册。
"""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from web.backend.deps import cleanup_deps, init_deps
from web.backend.logger_bridge import LoggerBridge
from web.backend.schemas import HealthInfo, ok_response
from web.backend.tasks import TaskRegistry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan：启动时初始化所有单例，关闭时清理。"""
    # ---- 启动 ----
    from config import ACTIVE_USER, MOMO_TOKEN, AI_PROVIDER, GEMINI_API_KEY, MIMO_API_KEY
    from database.connection import init_concurrent_system
    from database.schema import init_db
    from database.momo_words import get_unsynced_notes
    from database.utils import clean_for_maimemo
    from core.log_config import get_full_config
    from core.logger import setup_logger
    from core.maimemo_api import MaiMemoAPI
    from core.study_workflow import StudyWorkflow

    environment = os.getenv("MOMO_ENV", "development")
    config_file = os.getenv("MOMO_CONFIG_FILE", "config/logging.yaml")
    get_full_config(environment, config_file)

    logger = setup_logger(ACTIVE_USER, environment=environment, config_file=config_file)
    session_id = str(uuid.uuid4())
    logger.set_context(session_id=session_id)

    momo_api = MaiMemoAPI(MOMO_TOKEN)

    # AI 客户端
    if AI_PROVIDER == "mimo":
        from core.mimo_client import MimoClient
        ai_client = MimoClient(MIMO_API_KEY)
    else:
        from core.gemini_client import GeminiClient
        ai_client = GeminiClient(GEMINI_API_KEY)

    # 并发系统 & 数据库
    init_concurrent_system()
    init_db()

    # Workflow — 使用 NullUIManager（Web 无需 CLI 交互）
    class _NullUI:
        """空 UI 实现，Web 后端不需要 CLI 交互。"""
        def __getattr__(self, name):
            return lambda *a, **kw: None

    workflow = StudyWorkflow(
        logger=logger,
        ai_client=ai_client,
        momo_api=momo_api,
        ui_manager=_NullUI(),
    )

    # 启动时自动入队未同步笔记
    unsynced = get_unsynced_notes()
    if unsynced:
        logger.info(f"发现 {len(unsynced)} 条待同步笔记，正在入队...")
        for note in unsynced:
            workflow.sync_manager.queue_maimemo_sync(
                note["voc_id"],
                note.get("spelling", ""),
                clean_for_maimemo(note.get("basic_meanings", "")),
                ["雅思"],
                force_sync=True,
            )

    # TaskRegistry + LoggerBridge
    task_registry = TaskRegistry()
    logger_bridge = LoggerBridge(task_registry)
    logger_bridge.attach(logger)

    # 注册到依赖注入
    init_deps(
        active_user=ACTIVE_USER,
        logger=logger,
        momo_api=momo_api,
        ai_client=ai_client,
        workflow=workflow,
        task_registry=task_registry,
        logger_bridge=logger_bridge,
    )

    logger.info(f"[Web] 后端已启动，用户: {ACTIVE_USER}，AI: {AI_PROVIDER}", module="web.app")

    yield  # --- 应用运行中 ---

    # ---- 关闭 ----
    logger.info("[Web] 后端正在关闭...", module="web.app")
    logger_bridge.detach(logger)
    cleanup_deps()
    from database.connection import cleanup_concurrent_system
    cleanup_concurrent_system()


def create_app() -> FastAPI:
    """FastAPI 工厂函数。"""
    app = FastAPI(
        title="MOMO Study Agent Web UI",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS — 开发期间允许前端 dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- 注册路由 ----
    from web.backend.routers.session import router as session_router
    from web.backend.routers.tasks import router as tasks_router
    from web.backend.routers.preflight import router as preflight_router
    from web.backend.routers.study import router as study_router
    from web.backend.routers.words import router as words_router
    from web.backend.routers.stats import router as stats_router
    from web.backend.routers.sync import router as sync_router
    from web.backend.routers.users import router as users_router

    app.include_router(session_router)
    app.include_router(tasks_router)
    app.include_router(preflight_router)
    app.include_router(study_router)
    app.include_router(words_router)
    app.include_router(stats_router)
    app.include_router(sync_router)
    app.include_router(users_router)

    # ---- 健康检查 ----
    @app.get("/api/health")
    async def health():
        return ok_response(HealthInfo().model_dump())

    # ---- 生产模式：托管前端静态文件 ----
    frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
    if frontend_dist.is_dir():
        # 静态资源（JS/CSS/图片等）
        app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="static-assets")

        # SPA catch-all：所有非 /api 路径返回 index.html
        @app.get("/{full_path:path}")
        async def spa_catch_all(request: Request, full_path: str):
            # 不拦截 API 路径（理论上不会走到这里，因为 router 先匹配）
            if full_path.startswith("api/"):
                return {"ok": False, "error": {"code": "NOT_FOUND", "message": "API endpoint not found"}}
            # 尝试匹配静态文件（如 favicon.ico）
            file_path = frontend_dist / full_path
            if file_path.is_file():
                return FileResponse(str(file_path))
            # 否则返回 index.html（SPA 路由）
            return FileResponse(str(frontend_dist / "index.html"))

    return app
