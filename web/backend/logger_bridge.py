"""
web/backend/logger_bridge.py: LoggerBridge — 将 core/logger 事件桥接到 TaskRegistry 的 SSE 队列。

对现有 ContextLogger 打补丁，set_context(task_id=...) 后每次
info/warning/error 调用都把事件推入对应任务的 asyncio.Queue。
"""
from __future__ import annotations

import time
from typing import Any, Dict


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

                event = {
                    "type": "log",
                    "level": level,
                    "message": msg,
                    "module": kwargs.get("module", ""),
                    "ts": time.time(),
                }
                # 兼容两种写法：
                # 1) logger.info(msg, event="...", progress={...})
                # 2) logger.info(msg, extra={"event":"...", "progress": {...}})
                extra_payload = kwargs.get("extra")
                if isinstance(extra_payload, dict):
                    for key in ("event", "progress", "data"):
                        if key in extra_payload:
                            event[key] = extra_payload[key]
                for key in ("event", "progress", "data"):
                    if key in kwargs:
                        event[key] = kwargs[key]

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
