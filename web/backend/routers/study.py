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
import time
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Body, Depends, Query
from fastapi.concurrency import run_in_threadpool

from web.backend.deps import (
    get_active_user,
    get_ai_client,
    get_logger,
    get_momo_api,
    get_task_registry,
    get_user_context,
    get_workflow,
)
from web.backend.lock import acquire_profile_lock, get_profile_lock_holder, release_profile_lock
from web.backend.schemas import (
    ApiResponse,
    FutureItemsResponse,
    ProcessRequest,
    TaskRunResponse,
    TodayItemsResponse,
    error_response,
    ok_response,
)

router = APIRouter(prefix="/api/study", tags=["study"])

# 缓存配置：8 小时
TODAY_CACHE_TTL = 8 * 3600


def _submit_with_profile_lock(
    profile: str,
    registry,
    func,
    event_loop,
    logger,
):
    """提交重任务并在终态自动释放 profile lock。冲突时抛出 HTTPException 409。"""
    # 先尝试占位（task_id 尚未生成，用占位符）
    if not acquire_profile_lock(profile, "__pending__"):
        from fastapi import HTTPException
        holder = get_profile_lock_holder(profile)
        raise HTTPException(
            status_code=409,
            detail=error_response(
                "TASK_CONFLICT",
                f"用户 '{profile}' 已有任务正在运行（{holder}），请等待完成后重试",
            ),
        )

    import uuid as _uuid
    pending_task_id = _uuid.uuid4().hex[:8]  # 临时 ID 用于锁持有标记

    # 更新锁持有者为真实 task_id 占位
    from web.backend.lock import _profile_locks_guard, _profile_lock_holders
    with _profile_locks_guard:
        _profile_lock_holders[profile] = pending_task_id

    def _locked_run():
        # 切 DB globals 到此 profile 的 context，确保数据库读写不串台
        from web.backend.user_context import UserContextManager
        import web.backend.deps as _deps
        if _deps._context_manager:
            ctx = _deps._context_manager.get(profile)
            UserContextManager.prepare_for_task(ctx)
        try:
            func()
        finally:
            release_profile_lock(profile)

    task_id = registry.submit(_locked_run, event_loop=event_loop, logger=logger)

    # 更新锁持有者为真正的 task_id
    with _profile_locks_guard:
        _profile_lock_holders[profile] = task_id

    return task_id


@router.get("/today", response_model=ApiResponse[TodayItemsResponse])
async def get_today(
    refresh: bool = Query(default=False),
    user: str = Depends(get_active_user),
    ctx=Depends(get_user_context),
):
    """获取今日任务列表（带 8 小时缓存）。"""
    momo = ctx.momo_api
    
    # 检查缓存
    if not refresh:
        cache_entry = ctx.cache.get("today")
        if cache_entry:
            ts = cache_entry.get("ts", 0)
            if time.time() - ts < TODAY_CACHE_TTL:
                return ok_response(cache_entry["data"], user_id=user)

    try:
        res = await run_in_threadpool(momo.get_today_items, limit=500)
        items_raw = (res or {}).get("data", {}).get("today_items", [])
        
        # 状态回填：检查本地 DB 哪些已经同步成功了
        voc_ids = [str(it.get("voc_id")) for it in items_raw]
        from database.momo_words import get_sync_status_in_batch
        sync_statuses = await run_in_threadpool(get_sync_status_in_batch, voc_ids)
        
        items = []
        for it in items_raw:
            vid = str(it.get("voc_id"))
            # 如果 sync_status 为 1，说明本地已处理并同步过
            status = "done" if sync_statuses.get(vid) == 1 else None
            items.append({
                "voc_id": vid,
                "voc_spelling": it.get("voc_spelling") or it.get("spelling"),
                "voc_meanings": it.get("voc_meanings") or it.get("meanings") or "",
                "review_count": it.get("review_count") or 0,
                "familiarity_short": it.get("familiarity_short") or 0.0,
                "status": status
            })

        data = {
            "count": len(items),
            "items": items,
            "ts": time.time()
        }
        
        # 更新缓存
        ctx.cache["today"] = {
            "data": data,
            "ts": time.time()
        }
        
        return ok_response(data, user_id=user)
    except Exception as e:
        return error_response("MAIMO_API_ERROR", str(e), user_id=user)


@router.get("/future", response_model=ApiResponse[FutureItemsResponse])
async def get_future(
    days: int = Query(default=7, ge=1, le=30),
    user: str = Depends(get_active_user),
    momo=Depends(get_momo_api),
):
    """获取未来 N 天的学习计划。"""
    try:
        start_dt = datetime.now()
        end_dt = start_dt + timedelta(days=days)
        res = await run_in_threadpool(
            momo.query_study_records,
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


@router.post("/process", response_model=ApiResponse[TaskRunResponse])
async def process_today(
    request: ProcessRequest = Body(default_factory=ProcessRequest),
    user: str = Depends(get_active_user),
    momo=Depends(get_momo_api),
    workflow=Depends(get_workflow),
    logger=Depends(get_logger),
    registry=Depends(get_task_registry),
    ctx=Depends(get_user_context),
):
    """触发今日任务处理，立即返回 task_id，后台异步执行。"""
    momo = ctx.momo_api
    
    # 触发处理时清理缓存，确保下次获取的是最新状态
    ctx.cache.pop("today", None)
    
    try:
        res = await run_in_threadpool(momo.get_today_items, limit=500)
        items = (res or {}).get("data", {}).get("today_items", [])
    except Exception as e:
        return error_response("MAIMO_API_ERROR", str(e), user_id=user)

    if not items:
        return ok_response({"task_id": None, "message": "今日无待处理单词"}, user_id=user)

    # T6a: 如果指定了 voc_ids，只处理指定的单词
    if request.voc_ids:
        target_ids = set(request.voc_ids)
        items = [it for it in items if str(it.get("voc_id")) in target_ids]
        if not items:
            return ok_response({"task_id": None, "message": "指定的单词今日无需处理或不存在"}, user_id=user)

    loop = asyncio.get_running_loop()

    def _run():
        workflow.process_word_list(items, "今日任务")

    task_id = _submit_with_profile_lock(user, registry, _run, loop, logger)

    return ok_response({"task_id": task_id, "word_count": len(items)}, user_id=user)


@router.post("/process-future", response_model=ApiResponse[TaskRunResponse])
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
        res = await run_in_threadpool(
            momo.query_study_records,
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

    loop = asyncio.get_running_loop()

    def _run():
        workflow.process_word_list(records, f"未来 {days} 天计划")

    task_id = _submit_with_profile_lock(user, registry, _run, loop, logger)

    return ok_response({"task_id": task_id, "word_count": len(records), "days": days}, user_id=user)


@router.post("/iterate", response_model=ApiResponse[TaskRunResponse])
async def iterate(
    user: str = Depends(get_active_user),
    ai_client=Depends(get_ai_client),
    momo=Depends(get_momo_api),
    logger=Depends(get_logger),
    registry=Depends(get_task_registry),
):
    """触发智能迭代，立即返回 task_id。"""
    from core.iteration_manager import IterationManager

    loop = asyncio.get_running_loop()

    def _run():
        manager = IterationManager(ai_client=ai_client, momo_api=momo, logger=logger)
        manager.run_iteration()

    task_id = _submit_with_profile_lock(user, registry, _run, loop, logger)

    return ok_response({"task_id": task_id}, user_id=user)


@router.get("/iterate-candidates")
async def iterate_candidates(
    limit: int = Query(default=100, ge=1, le=500),
    user: str = Depends(get_active_user),
    logger=Depends(get_logger),
):
    """返回智能迭代候选词列表（薄弱词）。"""
    try:
        def _get_data():
            filter_obj = WeakWordFilter(logger)
            return filter_obj.get_weak_words_by_score(min_score=50.0, limit=limit)

        rows = await run_in_threadpool(_get_data)
        items = []
        for row in rows:
            items.append(
                {
                    "voc_id": str(row.get("voc_id", "")),
                    "voc_spelling": str(row.get("spelling", "")),
                    "voc_meanings": str(row.get("meanings", "") or ""),
                    "it_level": int(row.get("it_level", 0) or 0),
                    "weak_score": float(row.get("weak_score", 0.0) or 0.0),
                }
            )
        return ok_response({"count": len(items), "items": items}, user_id=user)
    except Exception as e:
        return error_response("ITERATE_CANDIDATES_ERROR", str(e), user_id=user)
