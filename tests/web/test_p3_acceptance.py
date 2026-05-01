"""
tests/web/test_p3_acceptance.py — P3 端到端验收测试。

固化 P3 阶段已落地的 row_status 事件流契约，让 P4-T1/T2 协议重构时
能在协议变化导致回归的瞬间被捕获，避免静默漂移。

覆盖范围：
1. LoggerBridge 把 logger.info(extra={"event":"row_status",...}) 桥接到
   TaskRegistry 事件流的 schema 稳定性
2. study/process happy path 的事件序列：状态运行 → row_status(running,ai_request)
   → row_status(running,ai_done) → row_status(done,sync_queued) → status done
3. study/process-future 与 study/iterate 同等结构
4. 失败路径：ai_result（AI 缺词）/ sync_conflict / sync_failed
5. 跳过细分：skipped / sync_pending / sync_conflict 行级状态
6. row_status 字段最小集合稳定性（item_id/status/phase/error）

注意：测试覆盖的是"事件流契约"而不是"业务逻辑"。当前协议为
type=log + event=row_status + data.rows[]，P4 改为 type=row_status 时
本测试需同步更新断言（这正是它存在的意义）。
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.backend import deps
from web.backend.logger_bridge import LoggerBridge
from web.backend.tasks import TaskRegistry
from web.backend.user_context import UserContext, UserContextManager
from web.backend.lock import (
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


def _row_status_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从事件流过滤出 row_status 事件（P4-T2 协议：type=row_status）。"""
    return [ev for ev in events if ev.get("type") == "row_status"]


def _row_states_for(events: List[Dict[str, Any]], item_id: str) -> List[Dict[str, Any]]:
    """提取某个单词的全部 row 事件载荷。"""
    out = []
    for ev in _row_status_events(events):
        rows = ev.get("rows") or []
        for row in rows:
            if str(row.get("item_id", "")).lower() == item_id.lower():
                out.append(row)
    return out


class _BridgedLogger:
    """带 context 的 logger 替身，可被 LoggerBridge attach。"""

    def __init__(self):
        self.context: Dict[str, Any] = {}

    def set_context(self, **kwargs):
        self.context.update(kwargs)

    def info(self, msg: str, **kwargs):
        pass

    def warning(self, msg: str, **kwargs):
        pass

    def error(self, msg: str, **kwargs):
        pass


def _make_mock_context(profile_name: str, registry: TaskRegistry) -> UserContext:
    logger = _BridgedLogger()
    bridge = LoggerBridge(registry)
    bridge.attach(logger)
    ctx = UserContext(
        profile_name=profile_name,
        logger=logger,
        momo_api=MagicMock(),
        ai_client=MagicMock(),
        workflow=MagicMock(),
        task_registry=registry,
        logger_bridge=bridge,
        db_path=f"/tmp/test-{profile_name}.db",
        env_path=f"/tmp/{profile_name}.env",
    )
    return ctx


def _make_context_manager(profiles: dict[str, UserContext]) -> UserContextManager:
    cm = UserContextManager.__new__(UserContextManager)
    cm._contexts = dict(profiles)
    cm._lock = threading.Lock()
    cm._warmup_state = {}
    return cm


# ---------------------------------------------------------------------------
# Fixture: clean profile lock state
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_profile_locks():
    with _profile_locks_guard:
        _profile_locks.clear()
        _profile_lock_holders.clear()
    yield
    with _profile_locks_guard:
        _profile_locks.clear()
        _profile_lock_holders.clear()


# ---------------------------------------------------------------------------
# 1. LoggerBridge 桥接 row_status 事件的 schema 稳定性
# ---------------------------------------------------------------------------
class TestLoggerBridgeRowStatus:
    """LoggerBridge 必须把 logger.info(extra={"event":"row_status",...}) 转成
    带 type=log + event=row_status + data.rows 的事件，进入 task 历史。"""

    def test_row_status_event_reaches_history(self):
        registry = TaskRegistry(max_workers=1)
        loop, thread = _create_loop()
        try:
            logger = _BridgedLogger()
            bridge = LoggerBridge(registry)
            bridge.attach(logger)

            def _emit():
                logger.info(
                    "[RowStatus] abandon AI 处理完成",
                    extra={
                        "event": "row_status",
                        "data": {
                            "rows": [
                                {
                                    "item_id": "abandon",
                                    "status": "running",
                                    "phase": "ai_done",
                                }
                            ]
                        },
                    },
                )

            task_id = registry.submit(_emit, event_loop=loop, logger=logger)
            _wait_terminal(registry, task_id)

            events = registry.get_events(task_id)
            row_events = _row_status_events(events)
            assert len(row_events) == 1, f"expected 1 row_status event, got {row_events}"

            ev = row_events[0]
            # 关键 schema 字段（P4-T2 后协议：type=row_status，rows 直接挂顶层）
            assert ev["type"] == "row_status"
            assert "rows" in ev
            row = ev["rows"][0]
            assert row["item_id"] == "abandon"
            assert row["status"] == "running"
            assert row["phase"] == "ai_done"
        finally:
            registry.shutdown()
            _close_loop(loop, thread)

    def test_row_status_supports_error_field(self):
        """失败行必须带 error 字段。"""
        registry = TaskRegistry(max_workers=1)
        loop, thread = _create_loop()
        try:
            logger = _BridgedLogger()
            bridge = LoggerBridge(registry)
            bridge.attach(logger)

            def _emit():
                logger.info(
                    "[RowStatus] foo 同步冲突",
                    extra={
                        "event": "row_status",
                        "data": {
                            "rows": [
                                {
                                    "item_id": "foo",
                                    "status": "error",
                                    "phase": "sync_conflict",
                                    "error": "远端释义与本地不一致",
                                }
                            ]
                        },
                    },
                )

            task_id = registry.submit(_emit, event_loop=loop, logger=logger)
            _wait_terminal(registry, task_id)

            row_states = _row_states_for(registry.get_events(task_id), "foo")
            assert len(row_states) == 1
            assert row_states[0]["status"] == "error"
            assert row_states[0]["phase"] == "sync_conflict"
            assert row_states[0]["error"] == "远端释义与本地不一致"
        finally:
            registry.shutdown()
            _close_loop(loop, thread)

    def test_row_status_batch_multiple_items(self):
        """同一事件可携带多行（study_workflow._run_ai_batch 模式）。"""
        registry = TaskRegistry(max_workers=1)
        loop, thread = _create_loop()
        try:
            logger = _BridgedLogger()
            bridge = LoggerBridge(registry)
            bridge.attach(logger)

            def _emit():
                logger.info(
                    "[RowStatus] 批次开始",
                    extra={
                        "event": "row_status",
                        "data": {
                            "rows": [
                                {"item_id": "alpha", "status": "running", "phase": "ai_request"},
                                {"item_id": "beta", "status": "running", "phase": "ai_request"},
                                {"item_id": "gamma", "status": "running", "phase": "ai_request"},
                            ]
                        },
                    },
                )

            task_id = registry.submit(_emit, event_loop=loop, logger=logger)
            _wait_terminal(registry, task_id)

            row_events = _row_status_events(registry.get_events(task_id))
            assert len(row_events) == 1
            rows = row_events[0]["rows"]
            assert {r["item_id"] for r in rows} == {"alpha", "beta", "gamma"}
            assert all(r["phase"] == "ai_request" for r in rows)
        finally:
            registry.shutdown()
            _close_loop(loop, thread)


# ---------------------------------------------------------------------------
# 2. /api/study/process happy path 的事件序列契约
# ---------------------------------------------------------------------------
def _emit_happy_path(logger, spells: List[str]):
    """复刻 study_workflow.process_word_list 的 row_status 发射序列。"""
    # AI 批次开始
    logger.info(
        "[RowStatus] 批次开始",
        extra={
            "event": "row_status",
            "data": {
                "rows": [
                    {"item_id": s.lower(), "status": "running", "phase": "ai_request"}
                    for s in spells
                ]
            },
        },
    )
    # AI 处理完成
    for s in spells:
        logger.info(
            f"[RowStatus] {s} AI 处理完成",
            extra={
                "event": "row_status",
                "data": {
                    "rows": [{"item_id": s.lower(), "status": "running", "phase": "ai_done"}]
                },
            },
        )
    # 入同步队列
    for s in spells:
        logger.info(
            f"[RowStatus] {s} 已入同步队列",
            extra={
                "event": "row_status",
                "data": {
                    "rows": [{"item_id": s.lower(), "status": "done", "phase": "sync_queued"}]
                },
            },
        )
    # 同步完成
    for s in spells:
        logger.info(
            f"[RowStatus] {s} 同步完成",
            extra={
                "event": "row_status",
                "data": {
                    "rows": [{"item_id": s.lower(), "status": "done", "phase": "sync_done"}]
                },
            },
        )


class TestStudyProcessHappyPath:
    """/api/study/process 触发后事件流应包含完整的 row_status 序列。"""

    def test_today_full_sequence(self):
        registry = TaskRegistry(max_workers=2)
        loop, thread = _create_loop()
        try:
            ctx = _make_mock_context("alice", registry)
            ctx.momo_api.get_today_items = MagicMock(
                return_value={
                    "data": {
                        "today_items": [
                            {"voc_id": "v1", "voc_spelling": "abandon", "voc_meanings": "v."},
                            {"voc_id": "v2", "voc_spelling": "bizarre", "voc_meanings": "adj."},
                        ]
                    }
                }
            )

            def _process_word_list(items, label):
                _emit_happy_path(ctx.logger, [it["voc_spelling"] for it in items])

            ctx.workflow.process_word_list = _process_word_list

            cm = _make_context_manager({"alice": ctx})

            app = FastAPI()
            from web.backend.routers.study import router as study_router
            app.include_router(study_router)
            app.dependency_overrides[deps.get_active_user] = lambda: "alice"
            app.dependency_overrides[deps.get_momo_api] = lambda: ctx.momo_api
            app.dependency_overrides[deps.get_workflow] = lambda: ctx.workflow
            app.dependency_overrides[deps.get_logger] = lambda: ctx.logger
            app.dependency_overrides[deps.get_task_registry] = lambda: registry

            with patch.object(deps, "_context_manager", cm):
                with TestClient(app, raise_server_exceptions=False) as client:
                    resp = client.post("/api/study/process")
                    assert resp.status_code == 200
                    body = resp.json()
                    assert body["ok"] is True
                    task_id = body["data"]["task_id"]
                    assert task_id

                    rec = _wait_terminal(registry, task_id, timeout=5.0)
                    assert rec is not None
                    assert rec.status == "done"

                    events = registry.get_events(task_id)

                    # 任务级 status 事件
                    statuses = [ev["status"] for ev in events if ev.get("type") == "status"]
                    assert "running" in statuses
                    assert "done" in statuses

                    # 每个词应经历 ai_request → ai_done → sync_queued → sync_done
                    for spell in ("abandon", "bizarre"):
                        states = _row_states_for(events, spell)
                        phases = [r.get("phase") for r in states]
                        assert "ai_request" in phases, f"{spell}: {phases}"
                        assert "ai_done" in phases, f"{spell}: {phases}"
                        assert "sync_queued" in phases, f"{spell}: {phases}"
                        assert "sync_done" in phases, f"{spell}: {phases}"
                        # 终态应当是 done
                        assert states[-1]["status"] == "done"
        finally:
            registry.shutdown()
            _close_loop(loop, thread)

    def test_today_returns_none_task_when_empty(self):
        """无待处理单词时不应启动任务（task_id=None），也不该占用 profile lock。"""
        registry = TaskRegistry(max_workers=1)
        loop, thread = _create_loop()
        try:
            ctx = _make_mock_context("alice", registry)
            ctx.momo_api.get_today_items = MagicMock(
                return_value={"data": {"today_items": []}}
            )
            cm = _make_context_manager({"alice": ctx})

            app = FastAPI()
            from web.backend.routers.study import router as study_router
            app.include_router(study_router)
            app.dependency_overrides[deps.get_active_user] = lambda: "alice"
            app.dependency_overrides[deps.get_momo_api] = lambda: ctx.momo_api
            app.dependency_overrides[deps.get_workflow] = lambda: ctx.workflow
            app.dependency_overrides[deps.get_logger] = lambda: ctx.logger
            app.dependency_overrides[deps.get_task_registry] = lambda: registry

            with patch.object(deps, "_context_manager", cm):
                with TestClient(app, raise_server_exceptions=False) as client:
                    resp = client.post("/api/study/process")
                    assert resp.status_code == 200
                    body = resp.json()
                    assert body["data"]["task_id"] is None
                    # profile lock 不应被占用
                    with _profile_locks_guard:
                        assert "alice" not in _profile_lock_holders
        finally:
            registry.shutdown()
            _close_loop(loop, thread)


class TestStudyProcessFutureHappyPath:
    """/api/study/process-future 与 today 共享发射序列。"""

    def test_future_full_sequence(self):
        registry = TaskRegistry(max_workers=2)
        loop, thread = _create_loop()
        try:
            ctx = _make_mock_context("alice", registry)
            ctx.momo_api.query_study_records = MagicMock(
                return_value={
                    "data": {
                        "records": [
                            {"voc_id": "v9", "voc_spelling": "candidate", "voc_meanings": "n."},
                        ]
                    }
                }
            )

            def _process_word_list(items, label):
                _emit_happy_path(ctx.logger, [it["voc_spelling"] for it in items])

            ctx.workflow.process_word_list = _process_word_list
            cm = _make_context_manager({"alice": ctx})

            app = FastAPI()
            from web.backend.routers.study import router as study_router
            app.include_router(study_router)
            app.dependency_overrides[deps.get_active_user] = lambda: "alice"
            app.dependency_overrides[deps.get_momo_api] = lambda: ctx.momo_api
            app.dependency_overrides[deps.get_workflow] = lambda: ctx.workflow
            app.dependency_overrides[deps.get_logger] = lambda: ctx.logger
            app.dependency_overrides[deps.get_task_registry] = lambda: registry

            with patch.object(deps, "_context_manager", cm):
                with TestClient(app, raise_server_exceptions=False) as client:
                    resp = client.post("/api/study/process-future?days=3")
                    assert resp.status_code == 200
                    task_id = resp.json()["data"]["task_id"]
                    rec = _wait_terminal(registry, task_id, timeout=5.0)
                    assert rec.status == "done"

                    events = registry.get_events(task_id)
                    states = _row_states_for(events, "candidate")
                    phases = [r.get("phase") for r in states]
                    assert "ai_request" in phases
                    assert "sync_done" in phases
        finally:
            registry.shutdown()
            _close_loop(loop, thread)


# ---------------------------------------------------------------------------
# 3. 失败路径：ai_result / sync_conflict / sync_failed
# ---------------------------------------------------------------------------
class TestRowStatusFailureCases:
    """各类失败必须发出 status=error + phase 标识，且带 error 文本。"""

    @pytest.mark.parametrize(
        "phase,error_text",
        [
            ("ai_result", "AI 返回缺失该单词结果"),
            ("sync_conflict", "远端释义与本地不一致"),
            ("sync_failed", "invalid_res_id"),
        ],
    )
    def test_failure_phases(self, phase, error_text):
        registry = TaskRegistry(max_workers=1)
        loop, thread = _create_loop()
        try:
            logger = _BridgedLogger()
            bridge = LoggerBridge(registry)
            bridge.attach(logger)

            def _emit():
                logger.info(
                    f"[RowStatus] foo {phase}",
                    extra={
                        "event": "row_status",
                        "data": {
                            "rows": [
                                {
                                    "item_id": "foo",
                                    "status": "error",
                                    "phase": phase,
                                    "error": error_text,
                                }
                            ]
                        },
                    },
                )

            task_id = registry.submit(_emit, event_loop=loop, logger=logger)
            _wait_terminal(registry, task_id)

            states = _row_states_for(registry.get_events(task_id), "foo")
            assert len(states) == 1
            assert states[0]["status"] == "error"
            assert states[0]["phase"] == phase
            assert states[0]["error"] == error_text
        finally:
            registry.shutdown()
            _close_loop(loop, thread)


# ---------------------------------------------------------------------------
# 4. 跳过细分：skipped / sync_pending / sync_conflict
# ---------------------------------------------------------------------------
class TestSkipPhaseSubdivision:
    """已处理跳过的单词应按本地 sync_status 区分为 skipped / sync_pending / sync_conflict。"""

    def test_skip_phases_in_one_event(self):
        registry = TaskRegistry(max_workers=1)
        loop, thread = _create_loop()
        try:
            logger = _BridgedLogger()
            bridge = LoggerBridge(registry)
            bridge.attach(logger)

            def _emit():
                logger.info(
                    "[RowStatus] 本轮跳过单词状态回填",
                    extra={
                        "event": "row_status",
                        "data": {
                            "rows": [
                                {"item_id": "alpha", "status": "done", "phase": "skipped"},
                                {
                                    "item_id": "beta",
                                    "status": "pending",
                                    "phase": "sync_pending",
                                    "error": "本地已生成，待上传同步",
                                },
                                {
                                    "item_id": "gamma",
                                    "status": "error",
                                    "phase": "sync_conflict",
                                    "error": "云端释义冲突，待处理",
                                },
                            ]
                        },
                    },
                )

            task_id = registry.submit(_emit, event_loop=loop, logger=logger)
            _wait_terminal(registry, task_id)

            events = registry.get_events(task_id)
            rows = _row_status_events(events)[0]["rows"]
            by_id = {r["item_id"]: r for r in rows}
            assert by_id["alpha"]["phase"] == "skipped"
            assert by_id["alpha"]["status"] == "done"
            assert by_id["beta"]["phase"] == "sync_pending"
            assert by_id["beta"]["status"] == "pending"
            assert by_id["gamma"]["phase"] == "sync_conflict"
            assert by_id["gamma"]["status"] == "error"
        finally:
            registry.shutdown()
            _close_loop(loop, thread)


# ---------------------------------------------------------------------------
# 5. row_status 字段稳定性 — 当前协议下所有已知 phase 值
# ---------------------------------------------------------------------------
KNOWN_PHASES = {
    "ai_request",     # study_workflow._run_ai_batch
    "ai_done",        # study_workflow.process_word_list
    "ai_result",      # study_workflow 失败：AI 缺词
    "sync_queued",    # study_workflow 入同步队列
    "sync_done",      # sync_manager 同步成功
    "sync_pending",   # study_workflow 跳过细分
    "sync_conflict",  # sync_manager 冲突
    "sync_failed",    # sync_manager 失败
    "skipped",        # study_workflow 已处理跳过
}

ALLOWED_STATUSES = {"pending", "running", "done", "error"}


class TestRowStatusFieldStability:
    """所有 phase 都应是已知集合内成员；status 必须是 4 态之一。"""

    def test_known_phases_complete(self):
        # 这个测试存在的目的：phase 集合若新增/改名，本测试需要同步更新。
        # 失败提示开发者：协议正在漂移，请同步 docs / 前端。
        assert KNOWN_PHASES == {
            "ai_request",
            "ai_done",
            "ai_result",
            "sync_queued",
            "sync_done",
            "sync_pending",
            "sync_conflict",
            "sync_failed",
            "skipped",
        }

    def test_status_set_is_minimal(self):
        # 行级 status 仅这 4 态。前端 rowProgress.ts 也只识别这 4 个。
        assert ALLOWED_STATUSES == {"pending", "running", "done", "error"}

    @pytest.mark.parametrize("phase", sorted(KNOWN_PHASES))
    def test_each_phase_can_round_trip(self, phase):
        """每个已知 phase 值都能通过 LoggerBridge 完整往返。"""
        registry = TaskRegistry(max_workers=1)
        loop, thread = _create_loop()
        try:
            logger = _BridgedLogger()
            bridge = LoggerBridge(registry)
            bridge.attach(logger)

            status = "error" if phase in {"ai_result", "sync_conflict", "sync_failed"} else "done"

            def _emit():
                logger.info(
                    f"[RowStatus] x {phase}",
                    extra={
                        "event": "row_status",
                        "data": {
                            "rows": [{"item_id": "x", "status": status, "phase": phase}]
                        },
                    },
                )

            task_id = registry.submit(_emit, event_loop=loop, logger=logger)
            _wait_terminal(registry, task_id)

            states = _row_states_for(registry.get_events(task_id), "x")
            assert len(states) == 1
            assert states[0]["phase"] == phase
            assert states[0]["status"] in ALLOWED_STATUSES
        finally:
            registry.shutdown()
            _close_loop(loop, thread)
