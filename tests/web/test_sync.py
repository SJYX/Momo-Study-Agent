"""
tests/web/test_sync.py -- /api/sync/* endpoint tests.
"""
from __future__ import annotations
import contextlib
import sqlite3
from unittest.mock import MagicMock
import pytest
from web.backend import deps
from web.backend.routers.sync import router as sync_router


class TestSyncStatus:
    def test_sync_status_empty(self, app, test_db, monkeypatch, override_ctx):
        monkeypatch.setattr("database.connection._get_read_conn", lambda path: sqlite3.connect(test_db))
        _mock_backend = MagicMock()
        _mock_backend.op_lock_for.return_value = contextlib.nullcontext()
        monkeypatch.setattr("database.backends.get_active_backend", lambda: _mock_backend)
        monkeypatch.setattr("database.connection._is_main_write_singleton_conn", lambda conn: False)
        app.include_router(sync_router)
        override_ctx(test_db)
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/sync/status")
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["queue_depth"] == 0
        assert body["data"]["conflict_count"] == 0

    def test_sync_status_with_conflicts(self, app, test_db, monkeypatch, override_ctx):
        monkeypatch.setattr("database.connection._get_read_conn", lambda path: sqlite3.connect(test_db))
        _mock_backend = MagicMock()
        _mock_backend.op_lock_for.return_value = contextlib.nullcontext()
        monkeypatch.setattr("database.backends.get_active_backend", lambda: _mock_backend)
        monkeypatch.setattr("database.connection._is_main_write_singleton_conn", lambda conn: False)
        monkeypatch.setattr("database.word_repo.count_by_state", lambda *a, **kw: 1)
        monkeypatch.setattr(
            "database.word_repo.list_by_state",
            lambda *a, **kw: [
                {"voc_id": "v1", "spelling": "abandon", "basic_meanings": "v. abandon", "sync_status": 2, "created_at": "now"},
                {"voc_id": "v2", "spelling": "bizarre", "basic_meanings": "adj. bizarre", "sync_status": 2, "created_at": "now"},
            ],
        )
        app.include_router(sync_router)
        override_ctx(test_db)
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/sync/status")
        body = resp.json()
        assert body["data"]["queue_depth"] == 1
        assert body["data"]["conflict_count"] == 2

    def test_sync_status_conflicts_paged_default_20(self, app, test_db, monkeypatch, override_ctx):
        monkeypatch.setattr("database.connection._get_read_conn", lambda path: sqlite3.connect(test_db))
        _mock_backend = MagicMock()
        _mock_backend.op_lock_for.return_value = contextlib.nullcontext()
        monkeypatch.setattr("database.backends.get_active_backend", lambda: _mock_backend)
        monkeypatch.setattr("database.connection._is_main_write_singleton_conn", lambda conn: False)
        monkeypatch.setattr("database.word_repo.count_by_state", lambda *a, **kw: 25)
        monkeypatch.setattr(
            "database.word_repo.list_by_state",
            lambda *a, **kw: [
                {"voc_id": f"v{i}", "spelling": f"w{i}", "basic_meanings": "x", "sync_status": 2, "created_at": "now"}
                for i in range(20)
            ],
        )
        app.include_router(sync_router)
        override_ctx(test_db)
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/sync/status")
        body = resp.json()
        assert body["ok"] is True
        assert len(body["data"]["conflicts"]) == 20


class TestSyncFlush:
    def test_flush_success(self, client, mock_workflow):
        resp = client.post("/api/sync/flush")
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["flushed"] is True

    def test_flush_error(self, client, mock_workflow):
        mock_workflow.sync_manager.flush_pending_syncs = MagicMock(side_effect=RuntimeError("Sync failed"))
        resp = client.post("/api/sync/flush")
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "SYNC_FLUSH_ERROR"


class TestSyncRetry:
    def test_retry_no_conflicts(self, app, test_db, monkeypatch, override_ctx):
        monkeypatch.setattr("database.connection._get_read_conn", lambda path: sqlite3.connect(test_db))
        _mock_backend = MagicMock()
        _mock_backend.op_lock_for.return_value = contextlib.nullcontext()
        monkeypatch.setattr("database.backends.get_active_backend", lambda: _mock_backend)
        monkeypatch.setattr("database.connection._is_main_write_singleton_conn", lambda conn: False)
        app.include_router(sync_router)
        override_ctx(test_db)
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post("/api/sync/retry")
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["retried"] == 0

    def test_retry_with_conflicts(self, app, test_db, monkeypatch, mock_workflow, override_ctx):
        monkeypatch.setattr("database.connection._get_read_conn", lambda path: sqlite3.connect(test_db))
        _mock_backend = MagicMock()
        _mock_backend.op_lock_for.return_value = contextlib.nullcontext()
        monkeypatch.setattr("database.backends.get_active_backend", lambda: _mock_backend)
        monkeypatch.setattr("database.connection._is_main_write_singleton_conn", lambda conn: False)
        monkeypatch.setattr("database.utils.clean_for_maimemo", lambda x: x)
        monkeypatch.setattr(
            "database.word_repo.list_by_state",
            lambda *a, **kw: [{"voc_id": "v1", "spelling": "abandon", "basic_meanings": "v. abandon"}],
        )
        app.include_router(sync_router)
        ctx = override_ctx(test_db)
        ctx.workflow = mock_workflow
        app.dependency_overrides[deps.get_workflow] = lambda: mock_workflow
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post("/api/sync/retry")
        body = resp.json()
        assert body["data"]["retried"] == 1
