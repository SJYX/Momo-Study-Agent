"""
tests/web/test_stats.py — GET /api/stats/summary 测试。
"""
from __future__ import annotations

import sqlite3

import pytest

from web.backend import deps
from web.backend.routers.stats import router as stats_router


class TestStatsSummary:
    """GET /api/stats/summary"""

    def test_stats_empty_db(self, app, test_db, monkeypatch):
        """空数据库应返回全零统计。"""
        monkeypatch.setattr("database.connection._get_read_conn", lambda path: sqlite3.connect(test_db))
        monkeypatch.setattr("database.connection._get_singleton_conn_op_lock", lambda conn: None)
        monkeypatch.setattr("database.connection._is_main_write_singleton_conn", lambda conn: False)
        monkeypatch.setattr("database.momo_words.get_unsynced_notes", lambda: [])
        app.include_router(stats_router)
        app.dependency_overrides[deps.get_active_user] = lambda: "testuser"
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/stats/summary")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["total_words"] == 0
        assert data["processed_words"] == 0
        assert data["ai_batches"] == 0
        assert data["ai_notes_count"] == 0
        assert data["total_tokens"] == 0
        assert data["sync_queue_depth"] == 0
        assert data["weak_words_count"] == 0

    def test_stats_with_data(self, app, test_db, monkeypatch):
        """有数据时统计应正确。"""
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO processed_words (voc_id, spelling) VALUES (?, ?)", ("v1", "abandon")
        )
        conn.execute(
            "INSERT INTO ai_word_notes (voc_id, spelling, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            ("v1", "abandon"),
        )
        conn.execute(
            "INSERT INTO ai_batches (batch_id, total_tokens, total_latency_ms) VALUES (?, ?, ?)",
            ("b1", 500, 1200),
        )
        conn.execute(
            "INSERT INTO word_progress_history (voc_id, familiarity_short, review_count) VALUES (?, ?, ?)",
            ("v1", 1.5, 3),
        )
        conn.commit()
        conn.close()

        monkeypatch.setattr("database.connection._get_read_conn", lambda path: sqlite3.connect(test_db))
        monkeypatch.setattr("database.connection._get_singleton_conn_op_lock", lambda conn: None)
        monkeypatch.setattr("database.connection._is_main_write_singleton_conn", lambda conn: False)
        monkeypatch.setattr("database.momo_words.get_unsynced_notes", lambda: [{"voc_id": "v1"}])
        app.include_router(stats_router)
        app.dependency_overrides[deps.get_active_user] = lambda: "testuser"
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/stats/summary")
        app.dependency_overrides.clear()

        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["total_words"] == 1
        assert data["processed_words"] == 1
        assert data["ai_batches"] == 1
        assert data["ai_notes_count"] == 1
        assert data["total_tokens"] == 500
        assert data["sync_queue_depth"] == 1
        assert data["weak_words_count"] == 1  # familiarity_short < 3.0

    def test_stats_user_id(self, app, test_db, monkeypatch):
        """响应应包含 user_id。"""
        monkeypatch.setattr("database.connection._get_read_conn", lambda path: sqlite3.connect(test_db))
        monkeypatch.setattr("database.connection._get_singleton_conn_op_lock", lambda conn: None)
        monkeypatch.setattr("database.connection._is_main_write_singleton_conn", lambda conn: False)
        monkeypatch.setattr("database.momo_words.get_unsynced_notes", lambda: [])
        app.include_router(stats_router)
        app.dependency_overrides[deps.get_active_user] = lambda: "testuser"
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            body = c.get("/api/stats/summary").json()
        app.dependency_overrides.clear()

        assert body["user_id"] == "testuser"
