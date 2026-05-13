"""
web/backend/routers/stats.py: GET /api/stats/summary — 聚合统计。

从 ai_batches、processed_words、ai_word_notes 汇总关键指标。
新增 GET /api/stats/ops — Ops Monitor 四卡片聚合。
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, Header, Query

import config
from web.backend.deps import get_user_context
from web.backend.schemas import (
    ApiResponse,
    FailureHotspot,
    OpsStatsResponse,
    StatsSummary,
    TaskListItem,
    error_response,
    ok_response,
)

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/summary", response_model=ApiResponse[StatsSummary])
async def stats_summary(ctx = Depends(get_user_context)):
    """返回系统聚合统计信息。"""
    from database.connection import _get_read_conn, _get_singleton_conn_op_lock, _is_main_write_singleton_conn
    from database.word_repo import count_by_state
    from database.word_state import WordState

    user = ctx.profile_name
    conn = _get_read_conn(ctx.db_path)
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
        if not _is_main_write_singleton_conn(conn):
            conn.close()

    # 同步队列深度：仅计数，不拉取全量记录
    try:
        sync_queue_depth = count_by_state(WordState.LOCAL_READY, db_path=ctx.db_path)
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


_WINDOW_SECONDS = {
    "15m": 15 * 60,
    "1h": 60 * 60,
    "24h": 24 * 60 * 60,
}


@router.get("/ops", response_model=ApiResponse[OpsStatsResponse])
async def stats_ops(
    profile: str = Query(default=""),
    window: str = Query(default="1h", description="Time window: 15m / 1h / 24h"),
    x_momo_profile: str | None = Header(default=None),
):
    """Ops Monitor 四卡片聚合端点。一次返回任务态势、失败热点、系统健康、队列数据。"""
    import web.backend.deps as _deps
    if _deps._context_manager is None:
        return error_response("CONTEXT_NOT_READY", "UserContextManager 未初始化")

    prof = (profile or x_momo_profile or _deps._fallback_user or "default").strip().lower()
    try:
        ctx = _deps._context_manager.get(prof)
    except Exception:
        return error_response("PROFILE_NOT_FOUND", f"Profile not found: {prof}")

    registry = ctx.task_registry
    now = time.time()
    window_sec = _WINDOW_SECONDS.get(window, 3600)
    since = now - window_sec

    # --- 卡片1：任务态势 ---
    all_tasks = registry.list_all()
    tasks_running = sum(1 for t in all_tasks if t.get("status") == "running")
    tasks_done_1h = sum(1 for t in all_tasks if t.get("status") == "done" and (t.get("finished_at") or 0) >= since)
    tasks_error_1h = sum(1 for t in all_tasks if t.get("status") == "error" and (t.get("finished_at") or 0) >= since)

    # 最近 5 条任务
    sorted_tasks = sorted(all_tasks, key=lambda t: t.get("created_at", 0), reverse=True)[:5]
    recent_tasks = [TaskListItem(**t).model_dump() for t in sorted_tasks]

    # --- 卡片2：失败热点（从 event_history 聚合 error_type/error_code）---
    hotspot_map: dict[tuple[str, str | None], dict] = {}
    for t in all_tasks:
        if t.get("status") != "error":
            continue
        events = registry.get_events(t["task_id"])
        for ev in events:
            if ev.get("type") != "row_status":
                continue
            for row in ev.get("rows", []):
                if row.get("status") != "error":
                    continue
                etype = row.get("error_type") or row.get("phase") or "unknown"
                ecode = row.get("error_code")
                key = (etype, ecode)
                if key not in hotspot_map:
                    hotspot_map[key] = {"error_type": etype, "error_code": ecode, "count": 0, "latest_at": 0.0, "sample_items": []}
                entry = hotspot_map[key]
                entry["count"] += 1
                ts = ev.get("ts", 0)
                if ts > entry["latest_at"]:
                    entry["latest_at"] = ts
                if len(entry["sample_items"]) < 5:
                    entry["sample_items"].append({"item_id": row.get("item_id"), "error": row.get("error")})

    hotspots = sorted(hotspot_map.values(), key=lambda h: h["count"], reverse=True)[:5]
    failure_hotspots = [FailureHotspot(**h).model_dump() for h in hotspots]

    # --- 卡片3：系统健康 ---
    try:
        from core.preflight import run_preflight
        pf = run_preflight(root_dir=config.BASE_DIR, username=prof)
        system_ok = pf.get("ok", True)
        health_checks = pf.get("checks", [])
    except Exception:
        system_ok = True
        health_checks = []

    # --- 卡片4：队列 ---
    try:
        from database.connection import _get_read_conn as _rc1, _get_singleton_conn_op_lock as _lk1, _is_main_write_singleton_conn as _im1
        conn1 = _rc1(ctx.db_path)
        lock1 = _lk1(conn1)
        cur1 = conn1.cursor()
        try:
            if lock1 is not None:
                with lock1:
                    cur1.execute("SELECT COUNT(*) FROM ai_word_notes WHERE sync_status = 0 AND content_origin = 'ai_generated'")
                    row = cur1.fetchone()
            else:
                cur1.execute("SELECT COUNT(*) FROM ai_word_notes WHERE sync_status = 0 AND content_origin = 'ai_generated'")
                row = cur1.fetchone()
            sync_queue_depth = int((row or [0])[0] or 0)
        finally:
            cur1.close()
        if not _im1(conn1):
            conn1.close()
    except Exception:
        sync_queue_depth = 0

    try:
        from database.connection import _get_read_conn, _get_singleton_conn_op_lock, _is_main_write_singleton_conn
        conn = _get_read_conn(ctx.db_path)
        conn_lock = _get_singleton_conn_op_lock(conn)
        cur = conn.cursor()
        try:
            def _q(sql):
                cur.execute(sql)
                row = cur.fetchone()
                return row[0] if row else 0

            if conn_lock is not None:
                with conn_lock:
                    avg_latency = _q("SELECT COALESCE(AVG(total_latency_ms), 0) FROM ai_batches")
                    cur.close()
                conn.commit()
            else:
                try:
                    avg_latency = _q("SELECT COALESCE(AVG(total_latency_ms), 0) FROM ai_batches")
                finally:
                    cur.close()
                conn.commit()
        finally:
            if not _is_main_write_singleton_conn(conn):
                conn.close()
    except Exception:
        avg_latency = 0.0

    # sync conflicts
    try:
        sync_conflict_count = count_by_state(WordState.CONFLICT, db_path=ctx.db_path)
    except Exception:
        sync_conflict_count = 0

    return ok_response(OpsStatsResponse(
        tasks_running=tasks_running,
        tasks_done_1h=tasks_done_1h,
        tasks_error_1h=tasks_error_1h,
        recent_tasks=recent_tasks,
        failure_hotspots=failure_hotspots,
        system_ok=system_ok,
        health_checks=health_checks,
        sync_queue_depth=sync_queue_depth,
        sync_conflict_count=sync_conflict_count,
        avg_latency_ms=round(avg_latency, 1),
    ).model_dump(), user_id=prof)
