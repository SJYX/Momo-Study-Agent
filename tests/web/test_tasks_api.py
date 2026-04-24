import asyncio
import threading
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.backend.deps import get_task_registry
from web.backend.routers.tasks import router as tasks_router
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


def _wait_terminal(registry: TaskRegistry, task_id: str, timeout: float = 3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        rec = registry.get(task_id)
        if rec and rec.status in ("done", "error", "canceled"):
            return rec
        time.sleep(0.02)
    return registry.get(task_id)


def _build_client(registry: TaskRegistry):
    app = FastAPI()
    app.include_router(tasks_router)
    app.dependency_overrides[get_task_registry] = lambda: registry
    return TestClient(app)


def test_get_task_status_done():
    loop, thread = _create_loop()
    try:
        registry = TaskRegistry(max_workers=1)
        client = _build_client(registry)
        try:
            task_id = registry.submit(lambda: {"ok": True}, event_loop=loop, logger=None)
            rec = _wait_terminal(registry, task_id)
            assert rec is not None
            assert rec.status == "done"

            resp = client.get(f"/api/tasks/{task_id}")
            assert resp.status_code == 200
            payload = resp.json()
            assert payload["ok"] is True
            assert payload["data"]["task_id"] == task_id
            assert payload["data"]["status"] == "done"
            assert payload["data"]["result"] == {"ok": True}
            assert payload["data"]["error"] is None
        finally:
            client.close()
            registry.shutdown()
    finally:
        _close_loop(loop, thread)


def test_get_task_status_error():
    loop, thread = _create_loop()
    try:
        registry = TaskRegistry(max_workers=1)
        client = _build_client(registry)
        try:
            def _boom():
                raise RuntimeError("boom")

            task_id = registry.submit(_boom, event_loop=loop, logger=None)
            rec = _wait_terminal(registry, task_id)
            assert rec is not None
            assert rec.status == "error"

            resp = client.get(f"/api/tasks/{task_id}")
            assert resp.status_code == 200
            payload = resp.json()
            assert payload["ok"] is True
            assert payload["data"]["task_id"] == task_id
            assert payload["data"]["status"] == "error"
            assert payload["data"]["result"] is None
            assert "boom" in (payload["data"]["error"] or "")
        finally:
            client.close()
            registry.shutdown()
    finally:
        _close_loop(loop, thread)


def test_get_task_status_canceled():
    loop, thread = _create_loop()
    try:
        registry = TaskRegistry(max_workers=1)
        client = _build_client(registry)
        started = threading.Event()
        release = threading.Event()
        try:
            def _slow():
                started.set()
                release.wait(timeout=2.0)
                return {"ok": True}

            task_id = registry.submit(_slow, event_loop=loop, logger=None)
            assert started.wait(timeout=1.5)

            canceled = registry.cancel(task_id)
            assert canceled is True
            rec = _wait_terminal(registry, task_id)
            assert rec is not None
            assert rec.status == "canceled"

            resp = client.get(f"/api/tasks/{task_id}")
            assert resp.status_code == 200
            payload = resp.json()
            assert payload["ok"] is True
            assert payload["data"]["task_id"] == task_id
            assert payload["data"]["status"] == "canceled"
        finally:
            release.set()
            client.close()
            registry.shutdown()
    finally:
        _close_loop(loop, thread)
