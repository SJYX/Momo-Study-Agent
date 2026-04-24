"""
web/backend/routers/tasks.py: 任务状态查询 + SSE 进度流 + 取消。

GET  /api/tasks/{task_id}         — 任务状态
GET  /api/tasks/{task_id}/events  — SSE 进度流
POST /api/tasks/{task_id}/cancel  — 取消任务
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
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


@router.get("/{task_id}", response_model=ApiResponse[TaskStatusResponse])
async def get_task_status(task_id: str, registry=Depends(get_task_registry)):
    """查询任务状态。"""
    rec = registry.get(task_id)
    if rec is None:
        return JSONResponse(
            status_code=404,
            content=error_response("TASK_NOT_FOUND", f"Task not found: {task_id}"),
        )
    return ok_response(rec.to_dict())


@router.get("/{task_id}/events")
async def task_events(task_id: str, registry=Depends(get_task_registry)):
    """SSE 进度流：订阅任务事件直到任务结束。"""
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
async def cancel_task(task_id: str, registry=Depends(get_task_registry)):
    """取消一个运行中的任务。"""
    ok = registry.cancel(task_id)
    if not ok:
        return JSONResponse(
            status_code=400,
            content=error_response("TASK_CANCEL_ERROR", "Cannot cancel task (not found or already finished)"),
        )
    return ok_response({"canceled": True})
