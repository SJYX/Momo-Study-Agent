"""
web/backend/routers/stats.py: GET /api/stats/summary — 聚合统计。

从 ai_batches、processed_words、ai_word_notes 汇总关键指标。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from config import DB_PATH
from web.backend.deps import get_active_user
from web.backend.schemas import ok_response, error_response

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/summary")
async def stats_summary(user: str = Depends(get_active_user)):
    """返回系统聚合统计信息。"""
    from database.connection import _get_read_conn, _get_singleton_conn_op_lock, _is_main_write_conn

    conn = _get_read_conn(DB_PATH)
    conn_lock = _get_singleton_conn_op_lock(conn)
    cur = conn.cursor()

    try:
        def _q(sql):
            cur.execute(sql)
            row = cur.fetchone()
            return row[0] if row else 0

        if conn_lock is not None:
            with conn_lock:
                try:
                    total_words = _q("SELECT COUNT(DISTINCT voc_id) FROM word_progress_history")
                    processed_words = _q("SELECT COUNT(*) FROM processed_words")
                    ai_batches = _q("SELECT COUNT(*) FROM ai_batches")
                    total_tokens = _q("SELECT COALESCE(SUM(total_tokens), 0) FROM ai_batches")
                    avg_latency = _q("SELECT COALESCE(AVG(total_latency_ms), 0) FROM ai_batches")
                    ai_notes_count = _q("SELECT COUNT(*) FROM ai_word_notes")
                    weak_words = _q("""
                        SELECT COUNT(*) FROM (
                            SELECT h.voc_id
                            FROM word_progress_history h
                            JOIN (
                                SELECT voc_id, MAX(created_at) as mc
                                FROM word_progress_history GROUP BY voc_id
                            ) latest ON h.voc_id = latest.voc_id AND h.created_at = latest.mc
                            WHERE h.familiarity_short < 3.0
                        )
                    """)
                finally:
                    cur.close()
                conn.commit()
        else:
            try:
                total_words = _q("SELECT COUNT(DISTINCT voc_id) FROM word_progress_history")
                processed_words = _q("SELECT COUNT(*) FROM processed_words")
                ai_batches = _q("SELECT COUNT(*) FROM ai_batches")
                total_tokens = _q("SELECT COALESCE(SUM(total_tokens), 0) FROM ai_batches")
                avg_latency = _q("SELECT COALESCE(AVG(total_latency_ms), 0) FROM ai_batches")
                ai_notes_count = _q("SELECT COUNT(*) FROM ai_word_notes")
                weak_words = _q("""
                    SELECT COUNT(*) FROM (
                        SELECT h.voc_id
                        FROM word_progress_history h
                        JOIN (
                            SELECT voc_id, MAX(created_at) as mc
                            FROM word_progress_history GROUP BY voc_id
                        ) latest ON h.voc_id = latest.voc_id AND h.created_at = latest.mc
                        WHERE h.familiarity_short < 3.0
                    )
                """)
            finally:
                cur.close()
            conn.commit()
    finally:
        if not _is_main_write_conn(conn):
            conn.close()

    # 同步队列深度（通过 SyncManager 获取，但这里直接查 pending notes）
    try:
        from database.momo_words import get_unsynced_notes
        unsynced = get_unsynced_notes()
        sync_queue_depth = len(unsynced) if unsynced else 0
    except Exception:
        sync_queue_depth = 0

    return ok_response({
        "total_words": total_words,
        "processed_words": processed_words,
        "ai_batches": ai_batches,
        "ai_notes_count": ai_notes_count,
        "total_tokens": total_tokens,
        "avg_latency_ms": round(avg_latency, 1),
        "sync_queue_depth": sync_queue_depth,
        "weak_words_count": weak_words,
    }, user_id=user)