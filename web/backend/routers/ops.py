"""
web/backend/routers/ops.py: PLAYBOOK B5 指标系统的对外端点。

GET  /api/ops/metrics?profile=<name>          — 当前 profile 的滚动百分位快照
POST /api/ops/metrics/reset?profile=<name>    — 清空该 profile 的所有 metric 窗口（dev/debug）

设计要点：
- 进程内存的轻量指标层。仅当前进程可见，重启后丢失（PLAYBOOK B5 决议）。
- profile 维度隔离；空 profile 归到 sentinel "_global"。
- count=0 视为该 metric 尚无数据，前端可显示"暂无数据"占位。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from core.active_profile_registry import is_active
from core.metrics import get_metrics_collector
from web.backend.schemas import (
    ApiResponse,
    DbReplicaHealthResponse,
    MetricPercentiles,
    OpsMetricsResetResponse,
    OpsMetricsResponse,
    ok_response,
)

router = APIRouter(prefix="/api/ops", tags=["ops"])


_METRIC_FIELDS = [
    ("api", "api.duration_ms"),
    ("db_batch_write", "db.batch_write.duration_ms"),
    ("db_idle_sync", "db.idle_sync.duration_ms"),
    ("sync_queue_depth", "sync.queue.depth"),
    ("sync_task", "sync.task.duration_ms"),
]


def _normalize_profile(raw: Optional[str]) -> str:
    return (raw or "").strip().lower() or "_global"


@router.get("/metrics", response_model=ApiResponse[OpsMetricsResponse])
async def get_ops_metrics(
    profile: Optional[str] = Query(default=None, description="目标 profile；空则用 _global"),
):
    """返回指定 profile 的滚动百分位快照。"""
    prof = _normalize_profile(profile)
    coll = get_metrics_collector()

    payload: dict = {
        "profile": prof,
        "window_ttl_s": 300,
        "is_active_profile": is_active(prof) if prof != "_global" else False,
    }
    for response_field, metric_name in _METRIC_FIELDS:
        payload[response_field] = MetricPercentiles(
            p50=coll.percentile(prof, metric_name, 50),
            p95=coll.percentile(prof, metric_name, 95),
            p99=coll.percentile(prof, metric_name, 99),
            count=coll.count(prof, metric_name),
        ).model_dump()

    return ok_response(payload, user_id=prof)


@router.post("/metrics/reset", response_model=ApiResponse[OpsMetricsResetResponse])
async def reset_ops_metrics(
    profile: Optional[str] = Query(default=None, description="目标 profile；省略则清空全部"),
):
    """清空指标窗口。dev/debug 用——生产场景一般不需要主动调。"""
    coll = get_metrics_collector()
    if profile is None:
        coll.reset()
        return ok_response({"profile": None, "cleared": True})
    prof = _normalize_profile(profile)
    coll.reset(prof)
    return ok_response({"profile": prof, "cleared": True}, user_id=prof)


@router.get("/db/replica-health", response_model=ApiResponse[DbReplicaHealthResponse])
async def db_replica_health(
    profile: Optional[str] = Query(default=None),
):
    """Embedded Replica 健康快照：连接 + 同步性能 + 数据一致性。"""
    import os

    from database.execution_engine import get_db_sync_status, _write_queue_stats

    prof = _normalize_profile(profile)

    # 连接健康
    from database.connection import _main_write_conn_singleton, _main_write_conn_singleton_path
    conn_alive = _main_write_conn_singleton is not None
    is_cloud = bool(os.getenv("TURSO_DB_URL"))
    db_path = _main_write_conn_singleton_path or ""
    sync_status = get_db_sync_status()

    # 同步性能（从 MetricsCollector 取）
    coll = get_metrics_collector()
    sync_p50 = coll.percentile(prof, "db.idle_sync.duration_ms", 50)
    sync_p95 = coll.percentile(prof, "db.idle_sync.duration_ms", 95)
    sync_p99 = coll.percentile(prof, "db.idle_sync.duration_ms", 99)
    sync_count = coll.count(prof, "db.idle_sync.duration_ms")

    # 写队列统计
    wq = _write_queue_stats

    # 数据一致性
    schema_version = 0
    db_size_mb = 0.0
    try:
        import config as _cfg
        from database.connection import _get_read_conn, _get_singleton_conn_op_lock, _is_main_write_singleton_conn
        rconn = _get_read_conn(_cfg.DB_PATH)
        rlock = _get_singleton_conn_op_lock(rconn)
        rcur = rconn.cursor()
        try:
            if rlock is not None:
                with rlock:
                    rcur.execute("PRAGMA user_version")
                    row = rcur.fetchone()
                    schema_version = int(row[0]) if row else 0
            else:
                rcur.execute("PRAGMA user_version")
                row = rcur.fetchone()
                schema_version = int(row[0]) if row else 0
        finally:
            rcur.close()
        if not _is_main_write_singleton_conn(rconn):
            rconn.close()
        # 文件大小
        if os.path.exists(_cfg.DB_PATH):
            db_size_mb = round(os.path.getsize(_cfg.DB_PATH) / (1024 * 1024), 2)
    except Exception:
        pass

    return ok_response(DbReplicaHealthResponse(
        connection_alive=conn_alive,
        is_cloud=is_cloud,
        db_path=db_path,
        sync_in_progress=sync_status.get("syncing", False),
        last_sync_phase=sync_status.get("phase", ""),
        sync_p50_ms=sync_p50,
        sync_p95_ms=sync_p95,
        sync_p99_ms=sync_p99,
        sync_count=sync_count,
        write_queue_depth=max(0, wq.get("total_queued", 0) - wq.get("total_written", 0)),
        write_total_queued=wq.get("total_queued", 0),
        write_total_written=wq.get("total_written", 0),
        write_total_errors=wq.get("total_errors", 0),
        schema_version=schema_version,
        db_size_mb=db_size_mb,
    ).model_dump(), user_id=prof)
