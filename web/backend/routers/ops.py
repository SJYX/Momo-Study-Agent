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
