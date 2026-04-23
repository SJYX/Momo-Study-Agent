"""
web/backend/routers/tasks.py: 任务状态查询 + SSE 进度流 + 取消。

GET  /api/tasks/{task_id}         — 任务状态
GET  /api/tasks/{task_id}/events  — SSE 进度流
POST /api/tasks/{task_id}/cancel  — 取消任务
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from web.backend.deps import get_task_registry
from web.backend.schemas import error_response, ok_response

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/{task_id}")
async def get_task_status(task_id: str, registry=Depends(get_task_registry)):
    """查询任务状态。"""
    rec = registry.get(task_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return ok_response(rec.to_dict())


@router.get("/{task_id}/events")
async def task_events(task_id: str, registry=Depends(get_task_registry)):
    """SSE 进度流：订阅任务事件直到任务结束。"""
    rec = registry.get(task_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        async for event in registry.subscribe(task_id):
            import json
            yield {"event": event.get("type", "message"), "data": json.dumps(event, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str, registry=Depends(get_task_registry)):
    """取消一个运行中的任务。"""
    ok = registry.cancel(task_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Cannot cancel task (not found or already finished)")
    return ok_response({"canceled": True})