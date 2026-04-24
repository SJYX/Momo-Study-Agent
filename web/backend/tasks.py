"""
web/backend/tasks.py: TaskRegistry — 异步任务管理 + 事件队列（SSE 源）。

Web 后端接收请求后立即返回 task_id，后台线程池跑阻塞任务，
进度通过 LoggerBridge 推入 asyncio.Queue，再由 SSE 端点消费。
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


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
    # 创建任务时绑定的事件循环（用于线程安全投递 SSE 事件）
    event_loop: Optional[asyncio.AbstractEventLoop] = None
    # 线程 future（用于取消）
    future: Optional[Future] = None
    # 协作式取消标记
    cancel_requested: bool = False
    # 终态回放使用：保存最近事件历史
    event_history: List[dict] = field(default_factory=list)
    # 递增事件序号（用于回放去重）
    next_event_seq: int = 1

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
_EVENT_HISTORY_LIMIT = 2000


class TaskRegistry:
    """全局任务注册表。单例，由 app lifespan 创建并通过 deps 注入。"""

    def __init__(self, max_workers: int = 4, max_queue_size: int = 1000):
        self._tasks: Dict[str, TaskRecord] = {}
        self._tasks_lock = threading.Lock()
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
        if event_loop is None:
            raise RuntimeError("event_loop is required for TaskRegistry.submit")

        task_id = str(uuid.uuid4())
        eq: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue_size)

        rec = TaskRecord(task_id=task_id, event_queue=eq, event_loop=event_loop)
        with self._tasks_lock:
            self._tasks[task_id] = rec

        def _wrapper():
            # 自动设置 logger 的 task_id 上下文（解决闭包竞态）
            if logger is not None:
                try:
                    logger.set_context(task_id=task_id)
                except Exception:
                    pass

            with self._tasks_lock:
                rec.status = "running"
                rec.started_at = time.time()
                cancel_requested = rec.cancel_requested

            self._emit_event(rec, {
                "type": "status",
                "status": "running",
                "ts": rec.started_at,
            })

            if cancel_requested:
                with self._tasks_lock:
                    rec.status = "canceled"
                    rec.finished_at = time.time()
                self._emit_event(rec, {
                    "type": "status",
                    "status": "canceled",
                    "ts": rec.finished_at,
                })
                return

            try:
                result = func(*args, **kwargs)
                with self._tasks_lock:
                    rec.result = result
                    rec.finished_at = time.time()
                    if rec.cancel_requested:
                        rec.status = "canceled"
                    else:
                        rec.status = "done"
                    final_status = rec.status

                self._emit_event(rec, {
                    "type": "status",
                    "status": final_status,
                    "ts": rec.finished_at,
                })
            except Exception as exc:
                with self._tasks_lock:
                    rec.finished_at = time.time()
                    if rec.cancel_requested:
                        rec.status = "canceled"
                    else:
                        rec.status = "error"
                        rec.error = str(exc)
                    final_status = rec.status
                    final_error = rec.error

                self._emit_event(rec, {
                    "type": "status",
                    "status": final_status,
                    "error": final_error,
                    "ts": rec.finished_at,
                })

        future = self._executor.submit(_wrapper)
        with self._tasks_lock:
            rec.future = future
        return task_id

    # ------------------------------------------------------------------
    # 查询 & 操作
    # ------------------------------------------------------------------
    def get(self, task_id: str) -> Optional[TaskRecord]:
        with self._tasks_lock:
            return self._tasks.get(task_id)

    def push_event(self, task_id: str, event: dict) -> bool:
        """线程安全地向任务事件流推送一条事件。"""
        with self._tasks_lock:
            rec = self._tasks.get(task_id)
        if rec is None:
            return False
        self._emit_event(rec, event)
        return True

    def get_events(self, task_id: str) -> List[dict]:
        """获取任务事件历史（用于终态回放）。"""
        with self._tasks_lock:
            rec = self._tasks.get(task_id)
            if rec is None:
                return []
            return list(rec.event_history)

    def cancel(self, task_id: str) -> bool:
        event_to_emit: Optional[dict] = None
        with self._tasks_lock:
            rec = self._tasks.get(task_id)
            if rec is None:
                return False
            if rec.status not in ("pending", "running"):
                return False

            rec.cancel_requested = True
            if rec.status == "pending":
                if rec.future and not rec.future.done():
                    rec.future.cancel()
                rec.status = "canceled"
                rec.finished_at = time.time()
                event_to_emit = {
                    "type": "status",
                    "status": "canceled",
                    "ts": rec.finished_at,
                }
            else:
                event_to_emit = {
                    "type": "status",
                    "status": "running",
                    "cancel_requested": True,
                    "ts": time.time(),
                }
        if event_to_emit is not None:
            self._emit_event(rec, event_to_emit)
        return True

    # ------------------------------------------------------------------
    # SSE 事件流
    # ------------------------------------------------------------------
    async def subscribe(self, task_id: str):
        """Async generator，yield 任务事件直到任务结束。"""
        with self._tasks_lock:
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
        with self._tasks_lock:
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
    def _emit_event(self, rec: TaskRecord, event: dict):
        with self._tasks_lock:
            if "_seq" not in event:
                event = dict(event)
                event["_seq"] = rec.next_event_seq
                rec.next_event_seq += 1
            rec.event_history.append(event)
            if len(rec.event_history) > _EVENT_HISTORY_LIMIT:
                del rec.event_history[: len(rec.event_history) - _EVENT_HISTORY_LIMIT]
        self._put_event_sync(rec, event)

    @staticmethod
    def _put_event_sync(rec: TaskRecord, event: dict):
        """从工作线程向 asyncio.Queue 放入事件（线程安全）。"""
        if rec.event_queue is None or rec.event_loop is None:
            return

        try:
            def _enqueue():
                try:
                    rec.event_queue.put_nowait(event)
                except asyncio.QueueFull:
                    # 优先保留状态事件
                    if event.get("type") == "status":
                        try:
                            rec.event_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        rec.event_queue.put_nowait(event)

            if rec.event_loop.is_running():
                rec.event_loop.call_soon_threadsafe(_enqueue)
            else:
                rec.event_queue.put_nowait(event)
        except (asyncio.QueueFull, RuntimeError):
            pass  # 队列满时丢弃非关键事件
