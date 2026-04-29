"""
web/backend/app.py: FastAPI 工厂 — lifespan 初始化/清理 + 路由注册。

P1 改造：lifespan 创建 UserContextManager，profile 级资源按需初始化。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from web.backend.deps import cleanup_deps, init_deps
from web.backend.schemas import HealthInfo, ok_response
from web.backend.user_context import UserContextManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan：启动时创建 UserContextManager，关闭时清理所有 profile。"""
    # ---- 启动 ----
    import os
    from config import ACTIVE_USER

    # 创建 context manager
    context_manager = UserContextManager()

    # 预初始化启动用户（避免首次请求延迟）
    fallback_user = ACTIVE_USER or "default"
    try:
        context_manager.get(fallback_user)
    except Exception as e:
        print(f"⚠️ 预初始化用户 '{fallback_user}' 失败: {e}")

    # 注册到依赖注入
    init_deps(context_manager=context_manager, fallback_user=fallback_user)

    print(f"[Web] 后端已启动，默认用户: {fallback_user}")

    yield  # --- 应用运行中 ---

    # ---- 关闭 ----
    print("[Web] 后端正在关闭...")
    cleanup_deps()


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
        app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="static-assets")

        @app.get("/{full_path:path}")
        async def spa_catch_all(request: Request, full_path: str):
            if full_path.startswith("api/"):
                return {"ok": False, "error": {"code": "NOT_FOUND", "message": "API endpoint not found"}}
            file_path = frontend_dist / full_path
            if file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(frontend_dist / "index.html"))

    return app
