"""
web/backend/routers/tasks.py: 任务状态查询 + SSE 进度流 + 取消。

GET  /api/tasks/{task_id}         — 任务状态
GET  /api/tasks/{task_id}/events  — SSE 进度流
POST /api/tasks/{task_id}/cancel  — 取消任务
"""
from __future__ import annotations

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from web.backend.deps import get_task_registry
from web.backend.schemas import (
    ApiResponse,
    TaskCancelResponse,
    TaskStatusResponse,
    error_response,
    ok_response,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _profile_exists(profile: str) -> bool:
    try:
        from config import PROFILES_DIR
        from core.profile_manager import ProfileManager

        return profile in ProfileManager(PROFILES_DIR).list_profiles()
    except Exception:
        return False


def _resolve_registry(profile_query: str = "", x_momo_profile: str | None = None):
    """任务端点兼容 profile 来源：优先 query，其次 header。"""
    profile = (profile_query or x_momo_profile or "").strip().lower()

    import web.backend.deps as _deps
    if _deps._context_manager is None:
        raise RuntimeError("UserContextManager 未初始化")
    if not profile:
        profile = (_deps._fallback_user or "default").strip().lower()

    if hasattr(_deps._context_manager, "has") and not _deps._context_manager.has(profile) and not _profile_exists(profile):
        return None

    return _deps._context_manager.get(profile).task_registry


def _resolve_fallback_registry(request: Request):
    """仅在未指定 profile 的兼容路径下，按需获取 fallback registry。"""
    try:
        override = request.app.dependency_overrides.get(get_task_registry)
        if override:
            return override()
    except Exception:
        pass
    try:
        return get_task_registry()
    except Exception:
        return None


@router.get("/{task_id}", response_model=ApiResponse[TaskStatusResponse])
async def get_task_status(
    request: Request,
    task_id: str,
    profile: str = Query(default=""),
    x_momo_profile: str | None = Header(default=None),
):
    """查询任务状态。"""
    registry = None
    try:
        registry = _resolve_registry(profile_query=profile, x_momo_profile=x_momo_profile)
    except Exception:
        registry = _resolve_fallback_registry(request) if not (profile or x_momo_profile) else None
    if registry is None:
        return JSONResponse(
            status_code=404,
            content=error_response("TASK_NOT_FOUND", f"Task not found: {task_id}"),
        )
    rec = registry.get(task_id)
    if rec is None:
        return JSONResponse(
            status_code=404,
            content=error_response("TASK_NOT_FOUND", f"Task not found: {task_id}"),
        )
    return ok_response(rec.to_dict())


@router.get("/{task_id}/events")
async def task_events(
    task_id: str,
    profile: str = Query(default="", description="Profile name (required for SSE, since EventSource cannot set headers)"),
):
    """SSE 进度流：订阅任务事件直到任务结束。

    SSE (EventSource) 无法设置自定义 header，因此通过 query param 传递 profile。
    """
    # 通过 query param 解析 profile（SSE 无法设置 header）
    if not profile:
        return JSONResponse(
            status_code=400,
            content=error_response("PROFILE_REQUIRED", "SSE 连接必须通过 ?profile=xxx 指定 profile"),
        )

    import web.backend.deps as _deps
    if _deps._context_manager is None:
        return JSONResponse(
            status_code=500,
            content=error_response("CONTEXT_NOT_READY", "UserContextManager 未初始化"),
        )

    profile = profile.strip().lower()
    if hasattr(_deps._context_manager, "has") and not _deps._context_manager.has(profile) and not _profile_exists(profile):
        return JSONResponse(
            status_code=404,
            content=error_response("PROFILE_NOT_FOUND", f"Profile not initialized: {profile}"),
        )
    try:
        ctx = _deps._context_manager.get(profile)
    except Exception as e:
        return JSONResponse(
            status_code=404,
            content=error_response("CONTEXT_ERROR", f"获取 profile '{profile}' 上下文失败: {e}"),
        )
    registry = ctx.task_registry

    rec = registry.get(task_id)
    if rec is None:
        return JSONResponse(
            status_code=404,
            content=error_response("TASK_NOT_FOUND", f"Task not found: {task_id}"),
        )

    last_event_seq = -1

    async def event_generator():
        nonlocal last_event_seq
        # 新连接先回放事件历史，避免终态任务错过关键日志
        for event in registry.get_events(task_id):
            seq = event.get("_seq", -1) if isinstance(event, dict) else -1
            if seq != -1 and seq <= last_event_seq:
                continue
            if seq != -1:
                last_event_seq = seq
            import json
            yield {"event": event.get("type", "message"), "data": json.dumps(event, ensure_ascii=False)}

        async for event in registry.subscribe(task_id):
            seq = event.get("_seq", -1) if isinstance(event, dict) else -1
            if seq != -1 and seq <= last_event_seq:
                continue
            if seq != -1:
                last_event_seq = seq
            import json
            yield {"event": event.get("type", "message"), "data": json.dumps(event, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.post("/{task_id}/cancel", response_model=ApiResponse[TaskCancelResponse])
async def cancel_task(
    request: Request,
    task_id: str,
    profile: str = Query(default=""),
    x_momo_profile: str | None = Header(default=None),
):
    """取消一个运行中的任务。"""
    registry = None
    try:
        registry = _resolve_registry(profile_query=profile, x_momo_profile=x_momo_profile)
    except Exception:
        registry = _resolve_fallback_registry(request) if not (profile or x_momo_profile) else None
    if registry is None:
        return JSONResponse(
            status_code=400,
            content=error_response("TASK_CANCEL_ERROR", "Cannot cancel task (not found or already finished)"),
        )
    ok = registry.cancel(task_id)
    if not ok:
        return JSONResponse(
            status_code=400,
            content=error_response("TASK_CANCEL_ERROR", "Cannot cancel task (not found or already finished)"),
        )
    return ok_response({"canceled": True})
