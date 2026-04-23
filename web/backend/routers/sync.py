"""
web/backend/routers/sync.py: 同步状态端点。

GET  /api/sync/status — 队列深度 + 最近冲突列表
POST /api/sync/flush  — 触发一次立即收尾同步
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from config import DB_PATH
from web.backend.deps import get_active_user, get_workflow
from web.backend.schemas import ok_response, error_response

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status")
async def sync_status(
    limit: int = Query(default=20, ge=1, le=100),
    user: str = Depends(get_active_user),
):
    """返回同步队列深度和最近的冲突记录（sync_status=2）。"""
    from database.connection import _get_read_conn, _row_to_dict, _get_singleton_conn_op_lock, _is_main_write_singleton_conn
    from database.momo_words import get_unsynced_notes

    # 队列深度
    try:
        unsynced = get_unsynced_notes()
        queue_depth = len(unsynced) if unsynced else 0
    except Exception:
        queue_depth = 0

    # 冲突列表 (sync_status = 2)
    conn = _get_read_conn(DB_PATH)
    conn_lock = _get_singleton_conn_op_lock(conn)
    cur = conn.cursor()
    conflicts = []

    try:
        sql = """
            SELECT voc_id, spelling, basic_meanings, sync_status, updated_at AS created_at
            FROM ai_word_notes
            WHERE sync_status = 2
            ORDER BY updated_at DESC
            LIMIT ?
        """
        if conn_lock is not None:
            with conn_lock:
                try:
                    cur.execute(sql, (limit,))
                    conflicts = [_row_to_dict(cur, r) for r in cur.fetchall()]
                finally:
                    cur.close()
                conn.commit()
        else:
            try:
                cur.execute(sql, (limit,))
                conflicts = [_row_to_dict(cur, r) for r in cur.fetchall()]
            finally:
                cur.close()
            conn.commit()
    finally:
        if not _is_main_write_singleton_conn(conn):
            conn.close()

    return ok_response({
        "queue_depth": queue_depth,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }, user_id=user)


@router.post("/flush")
async def flush_sync(
    user: str = Depends(get_active_user),
    workflow=Depends(get_workflow),
):
    """触发一次立即收尾同步。"""
    try:
        workflow.sync_manager.flush_pending_syncs("Web手动触发")
        return ok_response({"flushed": True}, user_id=user)
    except Exception as e:
        return error_response("SYNC_FLUSH_ERROR", str(e), user_id=user)


@router.post("/retry")
async def retry_conflicts(
    user: str = Depends(get_active_user),
    workflow=Depends(get_workflow),
):
    """重试所有冲突的同步项（sync_status=2），将其重新入队。"""
    from database.connection import _get_read_conn, _row_to_dict, _get_singleton_conn_op_lock, _is_main_write_singleton_conn
    from database.utils import clean_for_maimemo

    conn = _get_read_conn(DB_PATH)
    conn_lock = _get_singleton_conn_op_lock(conn)
    cur = conn.cursor()
    conflicts = []

    try:
        sql = """
            SELECT voc_id, spelling, basic_meanings
            FROM ai_word_notes
            WHERE sync_status = 2
        """
        if conn_lock is not None:
            with conn_lock:
                try:
                    cur.execute(sql)
                    conflicts = [_row_to_dict(cur, r) for r in cur.fetchall()]
                finally:
                    cur.close()
                conn.commit()
        else:
            try:
                cur.execute(sql)
                conflicts = [_row_to_dict(cur, r) for r in cur.fetchall()]
            finally:
                cur.close()
            conn.commit()
    finally:
        if not _is_main_write_singleton_conn(conn):
            conn.close()

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
            )
            retried += 1
        except Exception:
            continue

    return ok_response({"retried": retried, "total_conflicts": len(conflicts)}, user_id=user)
