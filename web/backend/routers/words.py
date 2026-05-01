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
    from database.connection import _get_read_conn, _row_to_dict, _get_singleton_conn_op_lock, _is_main_write_singleton_conn

    user = ctx.profile_name
    conn = _get_read_conn(ctx.db_path)
    conn_lock = _get_singleton_conn_op_lock(conn)
    cur = conn.cursor()

    try:
        conditions = []
        params = []

        if search:
            conditions.append("n.spelling LIKE ?")
            params.append(f"%{search}%")
        if sync_status is not None:
            conditions.append("n.sync_status = ?")
            params.append(sync_status)
        if it_level is not None:
            conditions.append("n.it_level = ?")
            params.append(it_level)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * page_size

        count_sql = f"SELECT COUNT(*) FROM ai_word_notes n {where}"
        data_sql = f"""
            SELECT n.voc_id, n.spelling, n.basic_meanings, n.memory_aid,
                   n.it_level, n.sync_status, n.updated_at
            FROM ai_word_notes n
            {where}
            ORDER BY n.updated_at DESC
            LIMIT ? OFFSET ?
        """

        if conn_lock is not None:
            with conn_lock:
                try:
                    cur.execute(count_sql, params)
                    total = cur.fetchone()[0]
                    cur.execute(data_sql, params + [page_size, offset])
                    rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
                finally:
                    cur.close()
                conn.commit()
        else:
            try:
                cur.execute(count_sql, params)
                total = cur.fetchone()[0]
                cur.execute(data_sql, params + [page_size, offset])
                rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
            finally:
                cur.close()
            conn.commit()
    finally:
        if not _is_main_write_singleton_conn(conn):
            conn.close()

    return ok_response({
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": rows,
    }, user_id=user)


@router.get("/{voc_id}", response_model=ApiResponse[WordNoteDetail])
async def get_word_detail(voc_id: str, ctx = Depends(get_user_context)):
    """获取单个单词的完整笔记详情。"""
    from database.momo_words import get_local_word_note

    user = ctx.profile_name
    note = get_local_word_note(voc_id, db_path=ctx.db_path)
    if not note:
        return error_response("NOT_FOUND", f"Word note not found: {voc_id}", user_id=user)
    return ok_response(note, user_id=user)


@router.put("/{voc_id}")
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

    try:
        from database.connection import _execute_write_sql_sync
        from database.utils import get_timestamp_with_tz

        sql = "UPDATE ai_word_notes SET memory_aid = ?, updated_at = ? WHERE voc_id = ?"
        args = (memory_aid, get_timestamp_with_tz(), str(voc_id))
        
        # Web 环境下多用户并发，必须使用同步写入指定 db_path，不能使用全局的 _queue_write_operation
        _execute_write_sql_sync(sql, args, db_path=ctx.db_path)
        return ok_response({"updated": True, "voc_id": voc_id}, user_id=user)
    except Exception as e:
        return error_response("UPDATE_ERROR", str(e), user_id=user)


@router.get("/{voc_id}/iterations", response_model=ApiResponse[WordIterationsResponse])
async def get_word_iterations(voc_id: str, ctx = Depends(get_user_context)):
    """获取单词的迭代历史。"""
    from database.connection import _get_read_conn, _row_to_dict, _get_singleton_conn_op_lock, _is_main_write_singleton_conn

    user = ctx.profile_name
    conn = _get_read_conn(ctx.db_path)
    conn_lock = _get_singleton_conn_op_lock(conn)
    cur = conn.cursor()

    try:
        sql = """
            SELECT voc_id, stage AS iteration_type, score, justification, tags,
                   refined_content, raw_response, created_at
            FROM ai_word_iterations
            WHERE voc_id = ?
            ORDER BY created_at DESC
        """
        if conn_lock is not None:
            with conn_lock:
                try:
                    cur.execute(sql, (voc_id,))
                    rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
                finally:
                    cur.close()
                conn.commit()
        else:
            try:
                cur.execute(sql, (voc_id,))
                rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
            finally:
                cur.close()
            conn.commit()
    finally:
        if not _is_main_write_singleton_conn(conn):
            conn.close()

    return ok_response({"voc_id": voc_id, "iterations": rows}, user_id=user)
