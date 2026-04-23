"""
web/backend/tasks.py: TaskRegistry — 异步任务管理 + 事件队列（SSE 源）。

Web 后端接收请求后立即返回 task_id，后台线程池跑阻塞任务，
进度通过 LoggerBridge 推入 asyncio.Queue，再由 SSE 端点消费。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


@dataclass
class TaskRecord:
    """单个任务的状态快照。"""
    task_id: str
    status: str = "pending"  # pending | running | done | error | canceled
    result: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    # SSE 事件队列（asyncio.Queue 由 FastAPI 事件循环创建）
    event_queue: Optional[asyncio.Queue] = None
    # 线程 future（用于取消）
    future: Optional[Future] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# 任务结果保留时长（秒）
_RESULT_TTL = 30 * 60  # 30 分钟


class TaskRegistry:
    """全局任务注册表。单例，由 app lifespan 创建并通过 deps 注入。"""

    def __init__(self, max_workers: int = 4, max_queue_size: int = 1000):
        self._tasks: Dict[str, TaskRecord] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="web-task",
        )
        self._max_queue_size = max_queue_size

    # ------------------------------------------------------------------
    # 提交任务
    # ------------------------------------------------------------------
    def submit(
        self,
        func: Callable[..., Any],
        *args: Any,
        event_loop: asyncio.AbstractEventLoop | None = None,
        logger: Any = None,
        **kwargs: Any,
    ) -> str:
        """提交一个同步函数到后台线程池，立即返回 task_id。

        Args:
            func: 要执行的同步函数。
            event_loop: FastAPI 所在的事件循环，用于创建 asyncio.Queue。
            logger: 可选的 ContextLogger，wrapper 会在执行前自动设置 task_id 上下文。
        """
        task_id = str(uuid.uuid4())
        loop = event_loop or asyncio.get_event_loop()
        eq: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue_size)

        rec = TaskRecord(task_id=task_id, event_queue=eq)
        self._tasks[task_id] = rec

        def _wrapper():
            # 自动设置 logger 的 task_id 上下文（解决闭包竞态）
            if logger is not None:
                try:
                    logger.set_context(task_id=task_id)
                except Exception:
                    pass

            rec.status = "running"
            rec.started_at = time.time()
            self._put_event_sync(rec, {
                "type": "status",
                "status": "running",
                "ts": rec.started_at,
            })
            try:
                result = func(*args, **kwargs)
                rec.result = result
                rec.status = "done"
                rec.finished_at = time.time()
                self._put_event_sync(rec, {
                    "type": "status",
                    "status": "done",
                    "ts": rec.finished_at,
                })
            except Exception as exc:
                rec.status = "error"
                rec.error = str(exc)
                rec.finished_at = time.time()
                self._put_event_sync(rec, {
                    "type": "status",
                    "status": "error",
                    "error": rec.error,
                    "ts": rec.finished_at,
                })

        future = self._executor.submit(_wrapper)
        rec.future = future
        return task_id

    # ------------------------------------------------------------------
    # 查询 & 操作
    # ------------------------------------------------------------------
    def get(self, task_id: str) -> Optional[TaskRecord]:
        return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        rec = self._tasks.get(task_id)
        if rec is None:
            return False
        if rec.status not in ("pending", "running"):
            return False
        if rec.future and not rec.future.done():
            rec.future.cancel()
        rec.status = "canceled"
        rec.finished_at = time.time()
        return True

    # ------------------------------------------------------------------
    # SSE 事件流
    # ------------------------------------------------------------------
    async def subscribe(self, task_id: str):
        """Async generator，yield 任务事件直到任务结束。"""
        rec = self._tasks.get(task_id)
        if rec is None or rec.event_queue is None:
            return
        while True:
            try:
                event = await asyncio.wait_for(rec.event_queue.get(), timeout=30.0)
                yield event
                # 如果是终态，发送后结束
                if isinstance(event, dict) and event.get("type") == "status":
                    if event.get("status") in ("done", "error", "canceled"):
                        break
            except asyncio.TimeoutError:
                # 心跳：保持连接活跃
                yield {"type": "heartbeat", "ts": time.time()}

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------
    def cleanup_expired(self):
        """清理超时已完成任务的结果（可由后台定时器调用）。"""
        now = time.time()
        expired = [
            tid for tid, rec in self._tasks.items()
            if rec.status in ("done", "error", "canceled")
            and rec.finished_at
            and (now - rec.finished_at) > _RESULT_TTL
        ]
        for tid in expired:
            self._tasks.pop(tid, None)

    def shutdown(self):
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _put_event_sync(rec: TaskRecord, event: dict):
        """从工作线程向 asyncio.Queue 放入事件（线程安全）。"""
        if rec.event_queue is None:
            return
        loop = None
        try:
            # 尝试获取已有的事件循环（可能已被关闭）
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = None
        except RuntimeError:
            pass

        try:
            if loop and loop.is_running():
                loop.call_soon_threadsafe(rec.event_queue.put_nowait, event)
            else:
                # 无运行中的事件循环时，直接放入（队列可能暂时不可消费）
                rec.event_queue.put_nowait(event)
        except (asyncio.QueueFull, RuntimeError):
            pass  # 队列满时丢弃非关键事件