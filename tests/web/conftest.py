"""
tests/web/conftest.py — Web 后端测试共享 fixtures。

提供：
- mock_deps: 隔离的依赖注入（MaiMemo API / AI / Workflow / Logger）
- test_db: 临时 SQLite 数据库 + schema 初始化
- client: FastAPI TestClient + dependency_overrides
"""
from __future__ import annotations

import sqlite3
import sys
import threading
from asyncio import Queue
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# 在导入 web.backend 前，确保 config 已经以测试模式加载
# ---------------------------------------------------------------------------
_root = str(Path(__file__).resolve().parents[2])
if _root not in sys.path:
    sys.path.insert(0, _root)


# ====== Mock MaiMemo API ======
class MockMaiMemoAPI:
    """模拟墨墨 API，所有方法返回可预测数据。"""

    def __init__(self, token: str = "fake-token"):
        self.token = token
        self._closed = False

    def get_today_items(self, limit: int = 500) -> dict:
        return {
            "data": {
                "today_items": [
                    {"voc_id": "v1", "voc_spelling": "abandon", "voc_meanings": "v. 放弃"},
                    {"voc_id": "v2", "voc_spelling": "bizarre", "voc_meanings": "adj. 奇异的"},
                ]
            }
        }

    def query_study_records(self, start: str, end: str) -> dict:
        return {
            "data": {
                "records": [
                    {"voc_id": "v3", "voc_spelling": "candidate", "voc_meanings": "n. 候选人"},
                ]
            }
        }

    def close(self):
        self._closed = True


# ====== Mock AI Client ======
class MockAIClient:
    """模拟 AI 客户端。"""

    def __init__(self, api_key: str = "fake-key"):
        self.api_key = api_key

    def generate_with_instruction(self, prompt: str, instruction: str = "") -> tuple:
        return "OK", {"total_tokens": 10}

    def close(self):
        pass


# ====== Mock Workflow ======
class MockWorkflow:
    """模拟 StudyWorkflow，拦截所有业务调用。"""

    def __init__(self, *args, **kwargs):
        self.momo_api = kwargs.get("momo_api")
        self.ai_client = kwargs.get("ai_client")
        self.sync_manager = MagicMock()
        self.sync_manager.flush_pending_syncs = MagicMock()
        self.sync_manager.queue_maimemo_sync = MagicMock()
        self.process_calls: List[tuple] = []

    def process_word_list(self, items: list, label: str):
        self.process_calls.append((items, label))

    def shutdown(self):
        pass


# ====== Mock Logger ======
class MockLogger:
    """最小化 logger 替身。"""

    def __init__(self):
        self.context: Dict[str, Any] = {}
        self.messages: List[tuple] = []

    def set_context(self, **kwargs):
        self.context.update(kwargs)

    def info(self, msg: str, **kwargs):
        self.messages.append(("info", msg, kwargs))

    def warning(self, msg: str, **kwargs):
        self.messages.append(("warning", msg, kwargs))

    def error(self, msg: str, **kwargs):
        self.messages.append(("error", msg, kwargs))


# ====== Helper: 路由依赖 get_user_context 时使用 ======
def make_test_user_context(db_path: str, profile: str = "testuser"):
    """构造指向 test_db 的伪 UserContext，供路由依赖注入。

    P1 引入 UserContextManager 后，words/stats/sync 等路由通过
    Depends(get_user_context) 拿 ctx，测试需要 override 此依赖。
    """
    from web.backend.user_context import UserContext

    return UserContext(
        profile_name=profile,
        logger=MockLogger(),
        momo_api=MagicMock(),
        ai_client=MagicMock(),
        workflow=MagicMock(),
        task_registry=MagicMock(),
        logger_bridge=MagicMock(),
        db_path=db_path,
        env_path=f"/tmp/{profile}.env",
    )


def override_user_context(app, db_path: str, profile: str = "testuser"):
    """在 app.dependency_overrides 注入 get_user_context 与所有 ctx 衍生依赖。

    路由可能同时依赖 get_user_context 和 get_workflow/get_logger 等，
    所以这里把 ctx 的所有衍生 getter 都 override 一遍。
    """
    from web.backend import deps

    ctx = make_test_user_context(db_path, profile)
    app.dependency_overrides[deps.get_active_user] = lambda: profile
    app.dependency_overrides[deps.get_user_context] = lambda: ctx
    app.dependency_overrides[deps.get_logger] = lambda: ctx.logger
    app.dependency_overrides[deps.get_momo_api] = lambda: ctx.momo_api
    app.dependency_overrides[deps.get_ai_client] = lambda: ctx.ai_client
    app.dependency_overrides[deps.get_workflow] = lambda: ctx.workflow
    app.dependency_overrides[deps.get_task_registry] = lambda: ctx.task_registry
    app.dependency_overrides[deps.get_logger_bridge] = lambda: ctx.logger_bridge
    return ctx


@pytest.fixture
def override_ctx(app):
    """注入 get_user_context override，让用 Depends(get_user_context) 的路由
    拿到指向 test_db 的伪 ctx。tests 直接 `override_ctx(test_db)` 调用即可。"""
    def _do(db_path: str, profile: str = "testuser"):
        return override_user_context(app, db_path, profile)
    return _do


# ====== Task Registry ======
@pytest.fixture
def task_registry():
    """隔离的 TaskRegistry 实例。"""
    from web.backend.tasks import TaskRegistry

    reg = TaskRegistry(max_workers=2)
    yield reg
    reg.shutdown()


# ====== Temporary DB with Schema ======
@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """创建临时 SQLite DB 并初始化 schema。

    同时 monkeypatch database.connection 中的连接函数，
    使 words/stats/sync 路由读写临时 DB 而非真实数据。
    """
    db_path = str(tmp_path / "test_web.db")

    # 直接用 sqlite3 初始化 schema（绕过 cloud/local 分支）
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS processed_words (voc_id TEXT PRIMARY KEY, spelling TEXT, "
        "processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ai_word_notes ("
        "voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT, ielts_focus TEXT, collocations TEXT, "
        "traps TEXT, synonyms TEXT, discrimination TEXT, example_sentences TEXT, memory_aid TEXT, "
        "word_ratings TEXT, raw_full_text TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, "
        "batch_id TEXT, original_meanings TEXT, maimemo_context TEXT, content_origin TEXT, content_source_db TEXT, "
        "content_source_scope TEXT, it_level INTEGER DEFAULT 0, it_history TEXT, sync_status INTEGER DEFAULT 0, "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ai_word_iterations ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, voc_id TEXT NOT NULL, spelling TEXT, stage TEXT, it_level INTEGER, "
        "score REAL, justification TEXT, tags TEXT, refined_content TEXT, candidate_notes TEXT, raw_response TEXT, "
        "maimemo_context TEXT, batch_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "FOREIGN KEY(voc_id) REFERENCES ai_word_notes(voc_id))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS word_progress_history ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, voc_id TEXT, familiarity_short REAL, familiarity_long REAL, "
        "review_count INTEGER, it_level INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ai_batches ("
        "batch_id TEXT PRIMARY KEY, request_id TEXT, ai_provider TEXT, model_name TEXT, prompt_version TEXT, "
        "batch_size INTEGER, total_latency_ms INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, "
        "finish_reason TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.commit()
    conn.close()

    # monkeypatch config.DB_PATH
    monkeypatch.setattr("config.DB_PATH", db_path)

    return db_path


# ====== Mock Dependencies ======
@pytest.fixture
def mock_momo():
    return MockMaiMemoAPI()


@pytest.fixture
def mock_ai():
    return MockAIClient()


@pytest.fixture
def mock_workflow(mock_momo, mock_ai):
    return MockWorkflow(momo_api=mock_momo, ai_client=mock_ai)


@pytest.fixture
def mock_logger():
    return MockLogger()


# ====== FastAPI TestClient 工厂 ======
@pytest.fixture
def app():
    """创建轻量 FastAPI app（不走 lifespan，不连接真实数据库）。"""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


@pytest.fixture
def client(app, mock_momo, mock_ai, mock_workflow, mock_logger, task_registry):
    """TestClient + 全量依赖注入覆盖。"""
    from fastapi.testclient import TestClient

    from web.backend import deps

    # 注册路由
    from web.backend.routers.preflight import router as preflight_router
    from web.backend.routers.session import router as session_router
    from web.backend.routers.stats import router as stats_router
    from web.backend.routers.study import router as study_router
    from web.backend.routers.sync import router as sync_router
    from web.backend.routers.tasks import router as tasks_router
    from web.backend.routers.users import router as users_router
    from web.backend.routers.words import router as words_router

    for r in [
        session_router, tasks_router, preflight_router,
        study_router, words_router, stats_router,
        sync_router, users_router,
    ]:
        app.include_router(r)

    # 覆盖依赖
    app.dependency_overrides[deps.get_active_user] = lambda: "testuser"
    app.dependency_overrides[deps.get_momo_api] = lambda: mock_momo
    app.dependency_overrides[deps.get_ai_client] = lambda: mock_ai
    app.dependency_overrides[deps.get_workflow] = lambda: mock_workflow
    app.dependency_overrides[deps.get_logger] = lambda: mock_logger
    app.dependency_overrides[deps.get_task_registry] = lambda: task_registry

    # P1 后路由通过 get_user_context 拿 ctx；提供一个指向内存 mock 的伪 ctx
    _fake_ctx = make_test_user_context(db_path="/tmp/test-client.db")
    _fake_ctx.momo_api = mock_momo
    _fake_ctx.ai_client = mock_ai
    _fake_ctx.workflow = mock_workflow
    _fake_ctx.logger = mock_logger
    _fake_ctx.task_registry = task_registry
    app.dependency_overrides[deps.get_user_context] = lambda: _fake_ctx

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.dependency_overrides.clear()
