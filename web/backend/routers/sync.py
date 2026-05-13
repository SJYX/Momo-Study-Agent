"""
web/backend/routers/sync.py: 同步状态端点。

GET  /api/sync/status — 队列深度 + 最近冲突列表
POST /api/sync/flush  — 触发一次立即收尾同步
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

import config
from core.sync_priority import Priority
from database.word_state import WordState
from web.backend.deps import get_user_context, get_workflow
from web.backend.router_helpers import catch_api_errors
from web.backend.schemas import (
    ApiResponse,
    SyncFlushResponse,
    SyncRetryResponse,
    SyncStatusResponse,
    error_response,
    ok_response,
)

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status", response_model=ApiResponse[SyncStatusResponse])
async def sync_status(
    limit: int = Query(default=20, ge=1, le=100),
    ctx = Depends(get_user_context),
):
    """返回同步队列深度和最近的冲突记录（sync_status=2）。"""
    from core.feature_flags import is_enabled
    from database.word_repo import count_by_state, list_by_state

    user = ctx.profile_name

    # PLAYBOOK A4 Kill Switch：性能回退时关闭重查询，前端拿到 degraded=true 后显示降级文案
    if not is_enabled("SYNC_STATUS_HEAVY_QUERY_ENABLED", default=True):
        return ok_response({
            "queue_depth": -1,
            "conflict_count": 0,
            "conflicts": [],
            "degraded": True,
            "degraded_reason": "SYNC_STATUS_HEAVY_QUERY_ENABLED=False",
        }, user_id=user)

    queue_depth = count_by_state(WordState.LOCAL_READY, db_path=ctx.db_path)
    conflicts = list_by_state(WordState.CONFLICT, limit=limit, offset=0, db_path=ctx.db_path)

    return ok_response({
        "queue_depth": queue_depth,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }, user_id=user)


@router.post("/flush", response_model=ApiResponse[SyncFlushResponse])
@catch_api_errors("SYNC_FLUSH_ERROR")
async def flush_sync(
    ctx = Depends(get_user_context),
    workflow=Depends(get_workflow),
):
    """触发一次立即收尾同步。"""
    user = ctx.profile_name
    workflow.sync_manager.flush_pending_syncs("Web手动触发")
    return ok_response({"flushed": True}, user_id=user)


@router.post("/retry", response_model=ApiResponse[SyncRetryResponse])
async def retry_conflicts(
    ctx = Depends(get_user_context),
    workflow=Depends(get_workflow),
):
    """重试所有冲突的同步项（sync_status=2），将其重新入队。"""
    from core.feature_flags import is_enabled
    from database.utils import clean_for_maimemo
    from database.word_repo import list_by_state
    from database.word_state import WordState

    user = ctx.profile_name

    # PLAYBOOK A4 Kill Switch：性能回退时关闭重试入口，避免雪球。
    if not is_enabled("BACKGROUND_RETRY_ENABLED", default=True):
        return error_response(
            "BACKGROUND_RETRY_DISABLED",
            "后台重试功能当前已禁用（BACKGROUND_RETRY_ENABLED=False）",
            user_id=user,
        )

    conflicts = list_by_state(WordState.CONFLICT, limit=5000, offset=0, db_path=ctx.db_path)

    if not conflicts:
        return ok_response({"retried": 0, "message": "无冲突项需重试"}, user_id=user)

    retried = 0
    for c in conflicts:
        try:
            brief = clean_for_maimemo(c.get("basic_meanings", ""))
            workflow.sync_manager.queue_maimemo_sync(
                c["voc_id"],
                c.get("spelling", ""),
                brief,
                ["雅思"],
                force_sync=True,
                priority=Priority.P2,
                profile_name=user,
            )
            retried += 1
        except Exception:
            continue

    return ok_response({"retried": retried, "total_conflicts": len(conflicts)}, user_id=user)
