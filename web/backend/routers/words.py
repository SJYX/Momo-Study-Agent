"""
web/backend/routers/words.py: 单词库查询端点。

GET /api/words                   — 分页列出 ai_word_notes
GET /api/words/{voc_id}          — 单词笔记详情
GET /api/words/{voc_id}/iterations — 迭代历史
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

import config
from web.backend.deps import get_user_context
from web.backend.router_helpers import catch_api_errors
from web.backend.schemas import (
    ApiResponse,
    WordIterationsResponse,
    WordNoteDetail,
    WordsListResponse,
    error_response,
    ok_response,
)

router = APIRouter(prefix="/api/words", tags=["words"])


@router.get("", response_model=ApiResponse[WordsListResponse])
async def list_words(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    search: Optional[str] = Query(default=None),
    sync_status: Optional[int] = Query(default=None),
    it_level: Optional[int] = Query(default=None),
    ctx = Depends(get_user_context),
):
    """分页列出 ai_word_notes，支持搜索和筛选。"""
    from database.word_repo import count_word_notes, list_word_notes_paginated

    user = ctx.profile_name
    total = count_word_notes(
        search=search,
        sync_status=sync_status,
        it_level=it_level,
        db_path=ctx.db_path,
    )
    rows = list_word_notes_paginated(
        search=search,
        sync_status=sync_status,
        it_level=it_level,
        page=page,
        page_size=page_size,
        db_path=ctx.db_path,
    )

    return ok_response({
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": rows,
    }, user_id=user)


@router.get("/{voc_id}", response_model=ApiResponse[WordNoteDetail])
async def get_word_detail(voc_id: str, ctx = Depends(get_user_context)):
    """获取单个单词的完整笔记详情。"""
    from database.notes_repo import get_local_word_note

    user = ctx.profile_name
    note = get_local_word_note(voc_id, db_path=ctx.db_path)
    if not note:
        return error_response("NOT_FOUND", f"Word note not found: {voc_id}", user_id=user)
    return ok_response(note, user_id=user)


@router.put("/{voc_id}")
@catch_api_errors("UPDATE_ERROR")
async def update_word_note(
    voc_id: str,
    body: dict,
    ctx = Depends(get_user_context),
):
    """编辑单词笔记的 memory_aid 字段。"""
    user = ctx.profile_name
    memory_aid = body.get("memory_aid", "")
    if not memory_aid:
        return error_response("INVALID_INPUT", "memory_aid 不能为空", user_id=user)

    from database.word_repo import update_memory_aid

    ok = update_memory_aid(voc_id, memory_aid, db_path=ctx.db_path)
    if not ok:
        return error_response("UPDATE_ERROR", "更新 memory_aid 失败", user_id=user)
    return ok_response({"updated": True, "voc_id": voc_id}, user_id=user)


@router.get("/{voc_id}/iterations", response_model=ApiResponse[WordIterationsResponse])
async def get_word_iterations(voc_id: str, ctx = Depends(get_user_context)):
    """获取单词的迭代历史。"""
    from database.word_repo import get_word_iterations as get_word_iterations_repo

    user = ctx.profile_name
    rows = get_word_iterations_repo(voc_id, db_path=ctx.db_path)
    iterations = [
        {
            "voc_id": str(row.get("voc_id", voc_id)),
            "iteration_type": str(row.get("stage", row.get("iteration_type", ""))),
            "score": float(row.get("score", 0.0) or 0.0),
            "justification": str(row.get("justification", "") or ""),
            "tags": str(row.get("tags", "") or ""),
            "refined_content": str(row.get("refined_content", "") or ""),
            "raw_response": str(row.get("raw_response", "") or ""),
            "created_at": str(row.get("created_at", "") or ""),
        }
        for row in rows
    ]

    return ok_response({"voc_id": voc_id, "iterations": iterations}, user_id=user)
