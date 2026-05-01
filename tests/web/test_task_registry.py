import asyncio
import threading
import time

from web.backend.tasks import TaskRegistry


def _create_loop():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    return loop, thread


def _close_loop(loop, thread):
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)
    loop.close()


def test_task_registry_replay_events():
    loop, thread = _create_loop()
    try:
        registry = TaskRegistry(max_workers=2)
        ready = threading.Event()
        evt = threading.Event()
        captured_id = {}

        def _job():
            # 等外层把 task_id 写入闭包（避免 submit 后立即执行的竞态）
            ready.wait(timeout=2)
            registry.push_event(
                captured_id["id"],
                {"type": "log", "level": "info", "message": "hello", "ts": time.time()},
            )
            evt.set()
            return {"ok": True}

        task_id = registry.submit(_job, event_loop=loop, logger=None)
        captured_id["id"] = task_id
        ready.set()
        assert evt.wait(timeout=2)

        # 等任务结束
        deadline = time.time() + 3
        while time.time() < deadline:
            rec = registry.get(task_id)
            if rec and rec.status in ("done", "error", "canceled"):
                break
            time.sleep(0.05)

        events = registry.get_events(task_id)
        assert events
        assert any(e.get("type") == "log" and e.get("message") == "hello" for e in events)
        assert any(e.get("type") == "status" and e.get("status") == "done" for e in events)
        assert all("_seq" in e for e in events if isinstance(e, dict))
    finally:
        registry.shutdown()
        _close_loop(loop, thread)


def test_task_registry_cancel_pending():
    loop, thread = _create_loop()
    try:
        registry = TaskRegistry(max_workers=1)

        def _slow():
            time.sleep(1.5)
            return 1

        task_id = registry.submit(_slow, event_loop=loop, logger=None)
        ok = registry.cancel(task_id)
        assert ok is True

        rec = registry.get(task_id)
        assert rec is not None
        assert rec.cancel_requested is True
    finally:
        registry.shutdown()
        _close_loop(loop, thread)
