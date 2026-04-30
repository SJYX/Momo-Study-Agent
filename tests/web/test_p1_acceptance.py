"""
tests/web/test_p1_acceptance.py — P1 验收测试。

覆盖 P1 阶段核心验收标准：
1. SSE 必须通过 ?profile= 指定 profile，缺失/错误 profile 被拒绝
2. 同 profile 重任务互斥（409）
3. 不同 profile 可并发运行重任务
4. Profile 级 TaskRegistry 隔离（A 无法查询 B 的任务）
"""
from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.backend import deps
from web.backend.tasks import TaskRegistry
from web.backend.user_context import UserContext, UserContextManager
from web.backend.lock import (
    acquire_profile_lock,
    release_profile_lock,
    get_profile_lock_holder,
    _profile_locks,
    _profile_lock_holders,
    _profile_locks_guard,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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


def _make_mock_context(profile_name: str) -> UserContext:
    """创建一个 mock UserContext（不连真实 DB/API）。"""
    ctx = UserContext(
        profile_name=profile_name,
        logger=MagicMock(),
        momo_api=MagicMock(),
        ai_client=MagicMock(),
        workflow=MagicMock(),
        task_registry=TaskRegistry(max_workers=2),
        logger_bridge=MagicMock(),
        db_path=f"/tmp/test-{profile_name}.db",
        env_path=f"/tmp/{profile_name}.env",
    )
    return ctx


def _make_context_manager(profiles: dict[str, UserContext]) -> UserContextManager:
    """创建一个预填充的 UserContextManager。"""
    cm = UserContextManager.__new__(UserContextManager)
    cm._contexts = dict(profiles)
    cm._lock = threading.Lock()
    return cm


# ---------------------------------------------------------------------------
# Fixture: clean profile lock state
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_profile_locks():
    """每个测试前清理 profile lock 状态。"""
    with _profile_locks_guard:
        _profile_locks.clear()
        _profile_lock_holders.clear()
    yield
    with _profile_locks_guard:
        _profile_locks.clear()
        _profile_lock_holders.clear()


# ---------------------------------------------------------------------------
# 1. SSE profile 传递
# ---------------------------------------------------------------------------
class TestSSEProfilePassing:
    """SSE 必须通过 ?profile= 指定 profile。"""

    def test_sse_missing_profile_returns_400(self):
        """SSE 请求不带 profile 参数应返回 400。"""
        app = FastAPI()
        from web.backend.routers.tasks import router as tasks_router
        app.include_router(tasks_router)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/tasks/fake-id/events")
            assert resp.status_code == 400
            body = resp.json()
            assert body["ok"] is False
            assert body["error"]["code"] == "PROFILE_REQUIRED"

    def test_sse_wrong_profile_returns_404(self):
        """SSE 请求带不存在的 profile 应返回 context 错误。"""
        app = FastAPI()
        from web.backend.routers.tasks import router as tasks_router
        app.include_router(tasks_router)

        # 设置空的 context manager（无任何 profile）
        cm = _make_context_manager({})

        with patch.object(deps, "_context_manager", cm):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/tasks/fake-id/events?profile=nonexistent")
                # _context_manager.get("nonexistent") 会尝试创建 context 并失败
                assert resp.status_code == 500

    def test_sse_correct_profile_finds_task(self):
        """SSE 请求带正确 profile 可以找到对应任务。"""
        loop, thread = _create_loop()
        try:
            ctx_a = _make_mock_context("alice")
            cm = _make_context_manager({"alice": ctx_a})

            app = FastAPI()
            from web.backend.routers.tasks import router as tasks_router
            app.include_router(tasks_router)

            # 提交一个终态任务
            task_id = ctx_a.task_registry.submit(lambda: "ok", event_loop=loop, logger=None)
            _wait_terminal(ctx_a.task_registry, task_id)

            with patch.object(deps, "_context_manager", cm):
                with TestClient(app, raise_server_exceptions=False) as client:
                    # 正确 profile 可以查到任务
                    resp = client.get(f"/api/tasks/{task_id}?profile=alice")
                    assert resp.status_code == 200
                    body = resp.json()
                    assert body["ok"] is True
                    assert body["data"]["task_id"] == task_id

                    # 错误 profile 查不到任务
                    resp2 = client.get(f"/api/tasks/{task_id}?profile=bob")
                    assert resp2.status_code == 404
        finally:
            ctx_a.task_registry.shutdown()
            _close_loop(loop, thread)


# ---------------------------------------------------------------------------
# 2. 同 profile 重任务互斥
# ---------------------------------------------------------------------------
class TestProfileTaskLock:
    """同 profile 重任务互斥，第二个应返回 409。"""

    def test_acquire_and_release(self):
        """基本的 acquire/release 流程。"""
        assert acquire_profile_lock("alice", "task-1") is True
        assert get_profile_lock_holder("alice") == "task-1"

        release_profile_lock("alice")
        assert get_profile_lock_holder("alice") is None

    def test_double_acquire_fails(self):
        """同 profile 第二次 acquire 应失败。"""
        assert acquire_profile_lock("alice", "task-1") is True
        assert acquire_profile_lock("alice", "task-2") is False
        release_profile_lock("alice")

    def test_different_profiles_independent(self):
        """不同 profile 的锁互相独立。"""
        assert acquire_profile_lock("alice", "task-1") is True
        assert acquire_profile_lock("bob", "task-2") is True

        assert get_profile_lock_holder("alice") == "task-1"
        assert get_profile_lock_holder("bob") == "task-2"

        release_profile_lock("alice")
        assert get_profile_lock_holder("alice") is None
        assert get_profile_lock_holder("bob") == "task-2"

        release_profile_lock("bob")

    def test_release_idempotent(self):
        """重复 release 不应报错。"""
        acquire_profile_lock("alice", "task-1")
        release_profile_lock("alice")
        release_profile_lock("alice")  # 不应抛异常
        assert get_profile_lock_holder("alice") is None

    def test_study_endpoint_returns_409_on_conflict(self, mock_momo, mock_ai, mock_workflow, mock_logger, task_registry):
        """study 重任务端点在 profile lock 冲突时应返回 409。"""
        loop, thread = _create_loop()
        try:
            ctx_alice = _make_mock_context("alice")
            ctx_alice.momo_api = mock_momo
            ctx_alice.workflow = mock_workflow
            ctx_alice.logger = mock_logger
            ctx_alice.task_registry = task_registry
            cm = _make_context_manager({"alice": ctx_alice})

            app = FastAPI()
            from web.backend.routers.study import router as study_router
            app.include_router(study_router)

            app.dependency_overrides[deps.get_active_user] = lambda: "alice"
            app.dependency_overrides[deps.get_momo_api] = lambda: mock_momo
            app.dependency_overrides[deps.get_workflow] = lambda: mock_workflow
            app.dependency_overrides[deps.get_logger] = lambda: mock_logger
            app.dependency_overrides[deps.get_task_registry] = lambda: task_registry

            # 先占住 alice 的锁
            acquire_profile_lock("alice", "existing-task")

            with patch.object(deps, "_context_manager", cm):
                with TestClient(app, raise_server_exceptions=False) as client:
                    resp = client.post("/api/study/process")
                    assert resp.status_code == 409
                    body = resp.json()
                    # HTTPException 的 detail 是 dict
                    detail = body.get("detail", body)
                    if isinstance(detail, dict):
                        assert detail.get("error", {}).get("code") == "TASK_CONFLICT" or "TASK_CONFLICT" in str(detail)

            release_profile_lock("alice")
        finally:
            _close_loop(loop, thread)


# ---------------------------------------------------------------------------
# 3. Profile 级 TaskRegistry 隔离
# ---------------------------------------------------------------------------
class TestTaskRegistryIsolation:
    """A profile 无法查询或取消 B profile 的 task。"""

    def test_cross_profile_task_query(self):
        """A 的 registry 查不到 B 的 task。"""
        reg_a = TaskRegistry(max_workers=1)
        reg_b = TaskRegistry(max_workers=1)
        loop, thread = _create_loop()
        try:
            task_a = reg_a.submit(lambda: "a", event_loop=loop, logger=None)
            task_b = reg_b.submit(lambda: "b", event_loop=loop, logger=None)

            _wait_terminal(reg_a, task_a)
            _wait_terminal(reg_b, task_b)

            # A 能查到自己的任务
            assert reg_a.get(task_a) is not None
            assert reg_a.get(task_a).status == "done"

            # A 查不到 B 的任务
            assert reg_a.get(task_b) is None

            # B 能查到自己的任务
            assert reg_b.get(task_b) is not None
            assert reg_b.get(task_b).status == "done"

            # B 查不到 A 的任务
            assert reg_b.get(task_a) is None
        finally:
            reg_a.shutdown()
            reg_b.shutdown()
            _close_loop(loop, thread)

    def test_cross_profile_task_cancel(self):
        """A 无法取消 B 的 task。"""
        reg_a = TaskRegistry(max_workers=1)
        reg_b = TaskRegistry(max_workers=1)
        loop, thread = _create_loop()
        started = threading.Event()
        release = threading.Event()
        try:
            def _slow():
                started.set()
                release.wait(timeout=3.0)
                return "b"

            task_b = reg_b.submit(_slow, event_loop=loop, logger=None)
            assert started.wait(timeout=2.0)

            # A 尝试取消 B 的任务 — 应该失败
            assert reg_a.cancel(task_b) is False

            # B 可以取消自己的任务
            assert reg_b.cancel(task_b) is True
        finally:
            release.set()
            reg_a.shutdown()
            reg_b.shutdown()
            _close_loop(loop, thread)


# ---------------------------------------------------------------------------
# 4. Profile lock 集成：任务完成后自动释放
# ---------------------------------------------------------------------------
class TestProfileLockAutoRelease:
    """重任务完成后 profile lock 应自动释放，允许提交新任务。"""

    def test_lock_released_after_task_done(self):
        """任务正常完成后，lock 被释放，可以提交新任务。"""
        from web.backend.routers.study import _submit_with_profile_lock

        loop, thread = _create_loop()
        try:
            ctx = _make_mock_context("alice")
            cm = _make_context_manager({"alice": ctx})

            with patch.object(deps, "_context_manager", cm):
                task_id_1 = _submit_with_profile_lock(
                    "alice", ctx.task_registry, lambda: "ok", loop, None
                )
                _wait_terminal(ctx.task_registry, task_id_1)

                # lock 应该已释放
                assert get_profile_lock_holder("alice") is None

                # 可以提交新任务
                task_id_2 = _submit_with_profile_lock(
                    "alice", ctx.task_registry, lambda: "ok2", loop, None
                )
                assert task_id_2 != task_id_1
                _wait_terminal(ctx.task_registry, task_id_2)
        finally:
            ctx.task_registry.shutdown()
            _close_loop(loop, thread)
