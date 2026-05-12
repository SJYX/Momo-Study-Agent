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
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Body, Depends, Query
from fastapi.concurrency import run_in_threadpool

from config import DATA_DIR

from web.backend.deps import (
    get_active_user,
    get_ai_client,
    get_logger,
    get_momo_api,
    get_task_registry,
    get_user_context,
    get_workflow,
)
from web.backend.lock import (
    claim_profile_lock_with_placeholder,
    release_profile_lock,
    update_profile_lock_holder,
)
from web.backend.router_helpers import catch_api_errors
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

_TODAY_CACHE_DIR = Path(DATA_DIR) / "cache" / "today"

def _get_today_cache_path(profile: str) -> Path:
    date_str = datetime.now().strftime("%Y%m%d")
    return _TODAY_CACHE_DIR / f"today_{profile}_{date_str}.json"

def _clean_expired_today_caches() -> None:
    try:
        if not _TODAY_CACHE_DIR.exists():
            return
        today_str = datetime.now().strftime("%Y%m%d")
        for p in _TODAY_CACHE_DIR.glob("today_*.json"):
            parts = p.stem.split("_")
            if len(parts) >= 3:
                file_date = parts[-1]
                if file_date != today_str:
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:
                        pass
    except Exception:
        pass

def _load_today_items_raw(profile: str) -> Optional[list]:
    """从磁盘加载当天的 raw 列表（不带状态）"""
    path = _get_today_cache_path(profile)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
        if time.time() - data.get("ts", 0) < TODAY_CACHE_TTL:
            return data.get("items_raw")
    except Exception:
        pass
    return None

def _save_today_items_raw(profile: str, items_raw: list) -> None:
    try:
        _TODAY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _get_today_cache_path(profile)
        payload = {"ts": time.time(), "items_raw": items_raw}
        path.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
    except Exception:
        pass


def _submit_with_profile_lock(
    profile: str,
    registry,
    func,
    event_loop,
    logger,
    task_type: str = "today",
):
    """提交重任务并在终态自动释放 profile lock。冲突时抛出 HTTPException 409。

    两段式提交：先用占位 task_id 抢锁 → registry.submit 拿到真实 task_id → 替换持有者。
    所有锁内部状态访问通过 lock.py 的公开 API，不再戳私有变量。
    """
    acquired, prior_holder = claim_profile_lock_with_placeholder(profile)
    if not acquired:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=409,
            detail=error_response(
                "TASK_CONFLICT",
                f"用户 '{profile}' 已有任务正在运行（{prior_holder}），请等待完成后重试",
            ),
        )

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

    task_id = registry.submit(_locked_run, event_loop=event_loop, logger=logger,
                              task_type=task_type, profile=profile)

    update_profile_lock_holder(profile, task_id)

    return task_id


@router.get("/today", response_model=ApiResponse[TodayItemsResponse])
@catch_api_errors("MAIMO_API_ERROR")
async def get_today(
    refresh: bool = Query(default=False),
    user: str = Depends(get_active_user),
    ctx=Depends(get_user_context),
):
    """获取今日任务列表（支持多级持久化缓存与真实状态预加载）。"""
    # 顺带轻量清理过期的旧日缓存文件
    _clean_expired_today_caches()

    momo = ctx.momo_api

    # 1. 检查内存缓存（如果未强制刷新）
    if not refresh:
        cache_entry = ctx.cache.get("today")
        if cache_entry:
            ts = cache_entry.get("ts", 0)
            if time.time() - ts < TODAY_CACHE_TTL:
                return ok_response(cache_entry["data"], user_id=user)

    # 2. 检查磁盘持久化缓存（如果未强制刷新）
    items_raw = None
    if not refresh:
        items_raw = _load_today_items_raw(user)

    # 3. 若无任何可用缓存或要求强制刷新，调用云端接口拉取
    if items_raw is None:
        fetch_timeout_s = float(os.getenv("WEB_TODAY_ITEMS_TIMEOUT_S", "8"))
        try:
            res = await asyncio.wait_for(
                run_in_threadpool(momo.get_today_items, limit=500),
                timeout=fetch_timeout_s,
            )
            items_raw = (res or {}).get("data", {}).get("today_items", [])
            # 同步保存一份基础 raw 列表到本地磁盘，供冷启动快速重载
            _save_today_items_raw(user, items_raw)
        except asyncio.TimeoutError:
            # 云端抖动时优先保证接口可用：回退到磁盘缓存（可接受过期）
            stale_items = _load_today_items_raw(user)
            if stale_items is not None:
                items_raw = stale_items
            else:
                items_raw = []
            try:
                ctx.logger.warning(
                    f"[Web] get_today_items 超时({fetch_timeout_s}s)，已回退本地缓存",
                    module="study_router",
                )
            except Exception:
                pass

    # 4. 实时回填最新状态：切 DB context 并查询
    from web.backend.user_context import UserContextManager
    UserContextManager.prepare_for_task(ctx)

    voc_ids = [str(it.get("voc_id")) for it in items_raw if it.get("voc_id")]
    sync_statuses = {}
    if voc_ids:
        from database.momo_words import get_sync_status_in_batch
        sync_statuses = await run_in_threadpool(get_sync_status_in_batch, voc_ids)

    _SYNC_MAP = {
        0: "sync_pending",   # 本地已生成，等待同步
        1: "done",           # 远端已同步确认
        2: "sync_conflict",  # 远端释义不一致冲突
        3: "sync_queued",    # 已入后台队列排队中
        4: "syncing",        # 正在远端执行同步
        5: "sync_failed",    # 不可重试的终态失败
    }

    items = []
    for it in items_raw:
        vid = str(it.get("voc_id"))
        s_val = sync_statuses.get(vid)
        status = _SYNC_MAP.get(s_val) if s_val is not None else None
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

    # 5. 回写到进程内存缓存
    ctx.cache["today"] = {
        "data": data,
        "ts": time.time()
    }

    return ok_response(data, user_id=user)


@router.get("/future", response_model=ApiResponse[FutureItemsResponse])
@catch_api_errors("MAIMO_API_ERROR")
async def get_future(
    days: int = Query(default=7, ge=1, le=30),
    user: str = Depends(get_active_user),
    momo=Depends(get_momo_api),
):
    """获取未来 N 天的学习计划。"""
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


@router.post("/process", response_model=ApiResponse[TaskRunResponse])
@catch_api_errors("MAIMO_API_ERROR")
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

    res = await run_in_threadpool(momo.get_today_items, limit=500)
    items = (res or {}).get("data", {}).get("today_items", [])

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

    task_id = _submit_with_profile_lock(user, registry, _run, loop, logger, task_type="today")

    return ok_response({"task_id": task_id, "word_count": len(items)}, user_id=user)


@router.post("/process-future", response_model=ApiResponse[TaskRunResponse])
@catch_api_errors("MAIMO_API_ERROR")
async def process_future(
    days: int = Query(default=7, ge=1, le=30),
    user: str = Depends(get_active_user),
    momo=Depends(get_momo_api),
    workflow=Depends(get_workflow),
    logger=Depends(get_logger),
    registry=Depends(get_task_registry),
):
    """触发未来计划处理，立即返回 task_id。"""
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

    if not records:
        return ok_response({"task_id": None, "message": f"未来 {days} 天无待处理单词"}, user_id=user)

    loop = asyncio.get_running_loop()

    def _run():
        workflow.process_word_list(records, f"未来 {days} 天计划")

    task_id = _submit_with_profile_lock(user, registry, _run, loop, logger, task_type="future")

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

    task_id = _submit_with_profile_lock(user, registry, _run, loop, logger, task_type="iteration")

    return ok_response({"task_id": task_id}, user_id=user)


@router.get("/iterate-candidates")
@catch_api_errors("ITERATE_CANDIDATES_ERROR")
async def iterate_candidates(
    limit: int = Query(default=100, ge=1, le=500),
    user: str = Depends(get_active_user),
    logger=Depends(get_logger),
):
    """返回智能迭代候选词列表（薄弱词）。"""
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
