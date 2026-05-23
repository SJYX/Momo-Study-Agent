"""
web/backend/app.py: FastAPI 工厂 — lifespan 初始化/清理 + 路由注册。

P1 改造：lifespan 创建 UserContextManager，profile 级资源按需初始化。
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from web.backend.deps import cleanup_deps, init_deps
from web.backend.schemas import HealthInfo, ok_response
from web.backend.user_context import UserContextManager


# 这些前缀不依赖 profile DB, 也不应被 readiness 检查拦截。
# 业务路由都需要 DB ready 才能正常工作, 不在白名单内。
_DB_READY_EXEMPT_PREFIXES = (
    "/api/health",         # /api/health, /api/health/ready
    "/api/users",          # list/switch/create/validate/wizard/delete profile
    "/api/preflight",      # 检查云端连通 + 凭据有效, 不查本地 DB
    "/api/ops",            # 运维指标, 不依赖业务 DB schema
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan：启动时创建 UserContextManager，关闭时清理所有 profile。"""
    # ---- 启动 ----
    import os

    # 创建 context manager
    context_manager = UserContextManager()

    # 不在启动时初始化任何具体用户。
    # 仅保留 fallback 名称用于无 header 请求兼容（默认 default）。
    fallback_user = (os.getenv("MOMO_USER") or "default").strip().lower() or "default"

    # 注册到依赖注入（fallback_user 仅用于无 header 时的降级，不影响 profile 隔离）
    init_deps(context_manager=context_manager, fallback_user=fallback_user)

    print(f"[Web] 后端启动流程继续，fallback用户: {fallback_user}")

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

    # ── DB readiness gate ──
    # 业务路由调用前必须确认该 profile 的 DB 已经 init 完毕 (pyturso 首次 bootstrap
    # 可能要 80-141s)。期间一律返回 503 + Retry-After, 让前端轮询 /api/health/ready。
    @app.middleware("http")
    async def _gate_unready_db(request: Request, call_next):
        path = request.url.path
        # 非 API 请求 (前端静态资源) 直接放行
        if not path.startswith("/api/"):
            return await call_next(request)
        # 白名单端点 (健康检查 / 用户管理 / preflight / ops) 不依赖业务 DB
        if path.startswith(_DB_READY_EXEMPT_PREFIXES):
            return await call_next(request)

        # 业务路由: 检查当前 profile 的 DB 是否 ready
        import web.backend.deps as _deps
        if _deps._context_manager is None:
            return await call_next(request)  # 还没启动完, 让请求自然失败

        profile = (request.headers.get("X-Momo-Profile") or _deps._fallback_user or "").strip().lower()
        if not profile:
            return await call_next(request)

        # 只对已经触发过 warmup 的 profile 做检查 — 没触发过说明前端还没切用户,
        # 此时让请求自然走到 get_user_context, 它会触发 warmup。
        state = _deps._context_manager.get_warmup_state(profile)
        if state == "db_init_in_progress":
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "error": {
                        "code": "SYNCING",
                        "message": f"profile '{profile}' 正在首次同步云端数据库, 请稍候重试",
                        "warmup_state": state,
                    },
                },
                headers={"Retry-After": "5"},
            )

        return await call_next(request)

    # PLAYBOOK B5：API timing middleware
    # 对 /api/* 请求计时，记录到 MetricsCollector，给 B3 闲时引擎与 /api/ops/metrics 用
    @app.middleware("http")
    async def _record_api_timing(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        started_at = time.time()
        try:
            response = await call_next(request)
            return response
        finally:
            try:
                from core.metrics import get_metrics_collector
                elapsed_ms = (time.time() - started_at) * 1000.0
                profile = request.headers.get("X-Momo-Profile", "").strip().lower() or "_global"
                get_metrics_collector().record(profile, "api.duration_ms", float(elapsed_ms))
            except Exception:
                # 指标采集不应影响响应
                pass

    # ---- 注册路由 ----
    from web.backend.routers.session import router as session_router
    from web.backend.routers.tasks import router as tasks_router
    from web.backend.routers.preflight import router as preflight_router
    from web.backend.routers.study import router as study_router
    from web.backend.routers.words import router as words_router
    from web.backend.routers.stats import router as stats_router
    from web.backend.routers.sync import router as sync_router
    from web.backend.routers.users import router as users_router
    from web.backend.routers.ops import router as ops_router

    app.include_router(session_router)
    app.include_router(tasks_router)
    app.include_router(preflight_router)
    app.include_router(study_router)
    app.include_router(words_router)
    app.include_router(stats_router)
    app.include_router(sync_router)
    app.include_router(users_router)
    app.include_router(ops_router)

    # ---- 健康检查 ----
    @app.get("/api/health")
    async def health():
        from database.execution_engine import get_db_sync_status
        data = HealthInfo().model_dump()
        data["db_sync"] = get_db_sync_status()
        return ok_response(data)

    @app.get("/api/health/ready")
    async def health_ready(request: Request):
        """前端可以轮询此端点检查 profile DB 是否 init 完毕。

        返回:
          {
            "ready": bool,                            # True 表示该 profile 可以查 DB 了
            "warmup_state": "not_started"|"db_init_in_progress"|"db_init_done"|"done",
            "profile": "<profile_name>"
          }
        """
        import web.backend.deps as _deps
        profile = (request.headers.get("X-Momo-Profile") or _deps._fallback_user or "").strip().lower() or "default"
        if _deps._context_manager is None:
            return ok_response({"ready": False, "warmup_state": "not_started", "profile": profile})
        state = _deps._context_manager.get_warmup_state(profile)
        ready = state in ("db_init_done", "done")
        return ok_response({"ready": ready, "warmup_state": state, "profile": profile})

    # ---- 生产模式：托管前端静态文件 ----
    frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
    if frontend_dist.is_dir():
        # /assets/* 是 Vite 哈希命名的不可变资源（index-XXXX.js / index-XXXX.css），
        # 可以长期缓存。index.html 必须每次回源校验，否则浏览器永远拿不到新发布。
        IMMUTABLE_ASSETS = "public, max-age=31536000, immutable"
        NO_CACHE_HTML = "no-cache, no-store, must-revalidate"

        class _ImmutableAssetsStatic(StaticFiles):
            async def get_response(self, path: str, scope):
                resp = await super().get_response(path, scope)
                resp.headers["Cache-Control"] = IMMUTABLE_ASSETS
                return resp

        app.mount("/assets", _ImmutableAssetsStatic(directory=str(frontend_dist / "assets")), name="static-assets")

        @app.get("/{full_path:path}")
        async def spa_catch_all(request: Request, full_path: str):
            if full_path.startswith("api/"):
                return {"ok": False, "error": {"code": "NOT_FOUND", "message": "API endpoint not found"}}
            file_path = frontend_dist / full_path
            if file_path.is_file():
                # 非 /assets 的 dist 文件（favicon 等），按短缓存
                resp = FileResponse(str(file_path))
                resp.headers.setdefault("Cache-Control", "public, max-age=300")
                return resp
            # SPA fallback / index.html：必须每次校验，禁止粘滞缓存
            resp = FileResponse(str(frontend_dist / "index.html"))
            resp.headers["Cache-Control"] = NO_CACHE_HTML
            resp.headers["Pragma"] = "no-cache"
            return resp

    return app
