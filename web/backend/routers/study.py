"""
web/backend/routers/study.py: 学习相关端点。

GET  /api/study/today          — 今日任务列表
GET  /api/study/future?days=N  — 未来 N 天计划
POST /api/study/process        — 触发今日任务处理（返回 task_id）
POST /api/study/process-future — 触发未来计划处理（返回 task_id）
POST /api/study/iterate        — 触发智能迭代（返回 task_id）
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query

from web.backend.deps import (
    get_active_user,
    get_ai_client,
    get_logger,
    get_momo_api,
    get_task_registry,
    get_workflow,
)
from web.backend.schemas import ok_response, error_response

router = APIRouter(prefix="/api/study", tags=["study"])


@router.get("/today")
async def get_today(user: str = Depends(get_active_user), momo=Depends(get_momo_api)):
    """获取今日任务列表。"""
    try:
        res = momo.get_today_items(limit=500)
        items = (res or {}).get("data", {}).get("today_items", [])
        return ok_response({"count": len(items), "items": items}, user_id=user)
    except Exception as e:
        return error_response("MAIMO_API_ERROR", str(e), user_id=user)


@router.get("/future")
async def get_future(
    days: int = Query(default=7, ge=1, le=30),
    user: str = Depends(get_active_user),
    momo=Depends(get_momo_api),
):
    """获取未来 N 天的学习计划。"""
    try:
        start_dt = datetime.now()
        end_dt = start_dt + timedelta(days=days)
        res = momo.query_study_records(
            start_dt.strftime("%Y-%m-%dT00:00:00.000Z"),
            end_dt.strftime("%Y-%m-%dT23:59:59.000Z"),
        )
        items = (res or {}).get("data", {}).get("records", [])
        records = []
        for it in items:
            spell = it.get("voc_spelling") or it.get("spelling")
            vid = it.get("voc_id") or it.get("id")
            if spell and vid:
                records.append({
                    "voc_id": vid,
                    "voc_spelling": spell,
                    "voc_meanings": it.get("voc_meanings") or it.get("meanings") or "",
                })
        return ok_response({"days": days, "count": len(records), "items": records}, user_id=user)
    except Exception as e:
        return error_response("MAIMO_API_ERROR", str(e), user_id=user)


@router.post("/process")
async def process_today(
    user: str = Depends(get_active_user),
    momo=Depends(get_momo_api),
    workflow=Depends(get_workflow),
    logger=Depends(get_logger),
    registry=Depends(get_task_registry),
):
    """触发今日任务处理，立即返回 task_id，后台异步执行。"""
    try:
        res = momo.get_today_items(limit=500)
        items = (res or {}).get("data", {}).get("today_items", [])
    except Exception as e:
        return error_response("MAIMO_API_ERROR", str(e), user_id=user)

    if not items:
        return ok_response({"task_id": None, "message": "今日无待处理单词"}, user_id=user)

    loop = asyncio.get_event_loop()

    def _run():
        # logger.task_id 由 TaskRegistry.submit 的 wrapper 自动设置
        workflow.process_word_list(items, "今日任务")

    task_id = registry.submit(_run, event_loop=loop, logger=logger)

    return ok_response({"task_id": task_id, "word_count": len(items)}, user_id=user)


@router.post("/process-future")
async def process_future(
    days: int = Query(default=7, ge=1, le=30),
    user: str = Depends(get_active_user),
    momo=Depends(get_momo_api),
    workflow=Depends(get_workflow),
    logger=Depends(get_logger),
    registry=Depends(get_task_registry),
):
    """触发未来计划处理，立即返回 task_id。"""
    try:
        start_dt = datetime.now()
        end_dt = start_dt + timedelta(days=days)
        res = momo.query_study_records(
            start_dt.strftime("%Y-%m-%dT00:00:00.000Z"),
            end_dt.strftime("%Y-%m-%dT23:59:59.000Z"),
        )
        items = (res or {}).get("data", {}).get("records", [])
        records = []
        for it in items:
            spell = it.get("voc_spelling") or it.get("spelling")
            vid = it.get("voc_id") or it.get("id")
            if spell and vid:
                records.append({
                    "voc_id": vid,
                    "voc_spelling": spell,
                    "voc_meanings": it.get("voc_meanings") or it.get("meanings") or "",
                })
    except Exception as e:
        return error_response("MAIMO_API_ERROR", str(e), user_id=user)

    if not records:
        return ok_response({"task_id": None, "message": f"未来 {days} 天无待处理单词"}, user_id=user)

    loop = asyncio.get_event_loop()

    def _run():
        workflow.process_word_list(records, f"未来 {days} 天计划")

    task_id = registry.submit(_run, event_loop=loop, logger=logger)

    return ok_response({"task_id": task_id, "word_count": len(records), "days": days}, user_id=user)


@router.post("/iterate")
async def iterate(
    user: str = Depends(get_active_user),
    ai_client=Depends(get_ai_client),
    momo=Depends(get_momo_api),
    logger=Depends(get_logger),
    registry=Depends(get_task_registry),
):
    """触发智能迭代，立即返回 task_id。"""
    from core.iteration_manager import IterationManager

    loop = asyncio.get_event_loop()

    def _run():
        manager = IterationManager(ai_client=ai_client, momo_api=momo, logger=logger)
        manager.run_iteration()

    task_id = registry.submit(_run, event_loop=loop, logger=logger)

    return ok_response({"task_id": task_id}, user_id=user)