"""
tests/web/test_sync.py -- /api/sync/* endpoint tests.
"""
from __future__ import annotations
import sqlite3
from unittest.mock import MagicMock
import pytest
from web.backend import deps
from web.backend.routers.sync import router as sync_router


class TestSyncStatus:
    def test_sync_status_empty(self, app, test_db, monkeypatch):
        monkeypatch.setattr("database.connection._get_read_conn", lambda path: sqlite3.connect(test_db))
        monkeypatch.setattr("database.connection._get_singleton_conn_op_lock", lambda conn: None)
        monkeypatch.setattr("database.connection._is_main_write_singleton_conn", lambda conn: False)
        monkeypatch.setattr("database.momo_words.get_unsynced_notes", lambda: [])
        app.include_router(sync_router)
        app.dependency_overrides[deps.get_active_user] = lambda: "testuser"
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/sync/status")
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["queue_depth"] == 0
        assert body["data"]["conflict_count"] == 0

    def test_sync_status_with_conflicts(self, app, test_db, monkeypatch):
        conn = sqlite3.connect(test_db)
        conn.execute("INSERT INTO ai_word_notes (voc_id, spelling, basic_meanings, sync_status, updated_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)", ("v1","abandon","v. abandon",2))
        conn.execute("INSERT INTO ai_word_notes (voc_id, spelling, basic_meanings, sync_status, updated_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)", ("v2","bizarre","adj. bizarre",2))
        conn.commit()
        conn.close()
        monkeypatch.setattr("database.connection._get_read_conn", lambda path: sqlite3.connect(test_db))
        monkeypatch.setattr("database.connection._get_singleton_conn_op_lock", lambda conn: None)
        monkeypatch.setattr("database.connection._is_main_write_singleton_conn", lambda conn: False)
        monkeypatch.setattr("database.momo_words.get_unsynced_notes", lambda: [{"voc_id":"v1"}])
        app.include_router(sync_router)
        app.dependency_overrides[deps.get_active_user] = lambda: "testuser"
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/sync/status")
        body = resp.json()
        assert body["data"]["queue_depth"] == 1
        assert body["data"]["conflict_count"] == 2


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
    def test_retry_no_conflicts(self, app, test_db, monkeypatch):
        monkeypatch.setattr("database.connection._get_read_conn", lambda path: sqlite3.connect(test_db))
        monkeypatch.setattr("database.connection._get_singleton_conn_op_lock", lambda conn: None)
        monkeypatch.setattr("database.connection._is_main_write_singleton_conn", lambda conn: False)
        app.include_router(sync_router)
        app.dependency_overrides[deps.get_active_user] = lambda: "testuser"
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post("/api/sync/retry")
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["retried"] == 0

    def test_retry_with_conflicts(self, app, test_db, monkeypatch, mock_workflow):
        conn = sqlite3.connect(test_db)
        conn.execute("INSERT INTO ai_word_notes (voc_id, spelling, basic_meanings, sync_status, updated_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)", ("v1","abandon","v. abandon",2))
        conn.commit()
        conn.close()
        monkeypatch.setattr("database.connection._get_read_conn", lambda path: sqlite3.connect(test_db))
        monkeypatch.setattr("database.connection._get_singleton_conn_op_lock", lambda conn: None)
        monkeypatch.setattr("database.connection._is_main_write_singleton_conn", lambda conn: False)
        monkeypatch.setattr("database.utils.clean_for_maimemo", lambda x: x)
        app.include_router(sync_router)
        app.dependency_overrides[deps.get_active_user] = lambda: "testuser"
        app.dependency_overrides[deps.get_workflow] = lambda: mock_workflow
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post("/api/sync/retry")
        body = resp.json()
        assert body["data"]["retried"] == 1
