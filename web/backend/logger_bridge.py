"""
web/backend/logger_bridge.py: LoggerBridge — 将 core/logger 事件桥接到 TaskRegistry 的 SSE 队列。

对现有 ContextLogger 打补丁，set_context(task_id=...) 后每次
info/warning/error 调用都把事件推入对应任务的 asyncio.Queue。

P4-T2 协议迁移：bridge 现在按 logger.info(extra={...}) 的负载分流到不同的
TaskEvent 变体（schema 见 web/backend/schemas.py）：
  - extra.event == 'row_status'                       → type=row_status
  - extra.progress 存在 + extra.event 是 batch_*       → type=progress
  - 其他                                                → type=log

核心业务代码（core/study_workflow.py / core/sync_manager.py）继续以
logger.info(extra={...}) 的形式发事件，无需改 11 处发射点。
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional


# 把 study_workflow / iteration_manager 内部的 batch_* 事件名映射到 ProgressEvent.phase。
_PROGRESS_PHASES = {
    "batch_start": "ai_batch_start",
    "batch_done": "ai_batch_done",
    "batch_error": "ai_batch_error",
}


def _build_event(level: str, msg: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """根据 logger 调用现场决定事件 type 与 payload。返回符合新协议的 dict。

    迁移期约定：core 层的发射点不动（logger.info(extra={"event":..., "progress":..., "data":...})），
    在 bridge 层按 extra 字段路由。
    """
    extra_payload = kwargs.get("extra")
    extra: Dict[str, Any] = extra_payload if isinstance(extra_payload, dict) else {}
    # 顶层 kwargs 兼容（logger.info(msg, event=..., progress=...)）
    for k in ("event", "progress", "data"):
        if k in kwargs and k not in extra:
            extra[k] = kwargs[k]

    event_name = extra.get("event")
    ts = time.time()

    # row_status 事件：直接抽出 rows 列表
    if event_name == "row_status":
        rows = ((extra.get("data") or {}).get("rows") or [])
        return {"type": "row_status", "rows": rows, "ts": ts}

    # progress 事件：把 batch_* 事件配上 phase
    progress = extra.get("progress")
    if isinstance(progress, dict) and event_name in _PROGRESS_PHASES:
        phase = _PROGRESS_PHASES[event_name]
        # 兼容老 progress 字段名：current/total/batch_no/total_batches/words
        current = progress.get("current")
        total = progress.get("total")
        # batch 级事件没有 word-level current/total 时，用 batch_no/total_batches 作为兜底
        if current is None and "batch_no" in progress:
            current = progress["batch_no"]
        if total is None and "total_batches" in progress:
            total = progress["total_batches"]
        return {
            "type": "progress",
            "phase": phase,
            "current": int(current) if current is not None else 0,
            "total": int(total) if total is not None else 0,
            "message": msg,
            "ts": ts,
        }

    # 普通 log 事件
    return {
        "type": "log",
        "level": level,
        "message": msg,
        "module": kwargs.get("module", ""),
        "ts": ts,
    }


class LoggerBridge:
    """包装 ContextLogger，将日志事件转发到 TaskRegistry 的事件队列。

    用法：
        bridge = LoggerBridge(task_registry)
        bridge.attach(logger)         # 打补丁
        # ... logger.info("xxx") 自动推入对应 task 的队列
        bridge.detach(logger)         # 恢复原方法
    """

    def __init__(self, task_registry):
        self._registry = task_registry
        self._original_methods: Dict[int, Dict[str, Any]] = {}

    def attach(self, logger) -> None:
        """给 logger 打补丁，拦截 info/warning/error 转发到 SSE 队列。"""
        oid = id(logger)
        if oid in self._original_methods:
            return  # 已经挂载

        originals = {
            "info": logger.info,
            "warning": logger.warning,
            "error": logger.error,
        }
        self._original_methods[oid] = originals

        def _make_proxy(level: str, orig):
            def proxy(msg: str, **kwargs: Any):
                # 先调原始方法（保证日志文件/控制台不变）
                orig(msg, **kwargs)

                # 如果有 task_id 上下文，推入事件队列
                ctx = getattr(logger, "context", {}) or {}
                task_id = ctx.get("task_id")
                if not task_id:
                    return

                rec = self._registry.get(task_id)
                if rec is None:
                    return

                event = _build_event(level, msg, kwargs)
                self._registry.push_event(task_id, event)

            return proxy

        logger.info = _make_proxy("info", originals["info"])
        logger.warning = _make_proxy("warning", originals["warning"])
        logger.error = _make_proxy("error", originals["error"])

    def detach(self, logger) -> None:
        """恢复 logger 的原始方法。"""
        oid = id(logger)
        originals = self._original_methods.pop(oid, None)
        if originals is None:
            return
        logger.info = originals["info"]
        logger.warning = originals["warning"]
        logger.error = originals["error"]
