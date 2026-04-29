"""
tests/web/test_words.py -- /api/words/* endpoint tests.
"""
from __future__ import annotations
import sqlite3
import pytest
from web.backend import deps
from web.backend.routers.words import router as words_router
import database.connection as db_conn


def _patch_db(app, test_db, monkeypatch):
    """Patch database.connection functions to use the test SQLite DB."""
    monkeypatch.setattr(db_conn, "_get_read_conn", lambda path: sqlite3.connect(test_db))
    monkeypatch.setattr(db_conn, "_get_singleton_conn_op_lock", lambda conn: None)
    monkeypatch.setattr(db_conn, "_is_main_write_singleton_conn", lambda conn: False)
    app.include_router(words_router)
    app.dependency_overrides[deps.get_active_user] = lambda: "testuser"


def _insert_word(conn, voc_id, spelling, **extra):
    """Insert a word note with all required string columns filled."""
    defaults = {
        "basic_meanings": "",
        "memory_aid": "",
        "sync_status": 0,
    }
    defaults.update(extra)
    conn.execute(
        "INSERT INTO ai_word_notes (voc_id, spelling, basic_meanings, memory_aid, sync_status, updated_at) "
        "VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)",
        (voc_id, spelling, defaults["basic_meanings"], defaults["memory_aid"], defaults["sync_status"]),
    )


class TestWordsList:
    def test_list_words_empty(self, app, test_db, monkeypatch):
        _patch_db(app, test_db, monkeypatch)
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/words")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 0

    def test_list_words_with_data(self, app, test_db, monkeypatch):
        conn = sqlite3.connect(test_db)
        _insert_word(conn, "v1", "abandon")
        _insert_word(conn, "v2", "bizarre")
        conn.commit()
        conn.close()
        _patch_db(app, test_db, monkeypatch)
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.get("/api/words")
        body = resp.json()
        assert body["data"]["total"] == 2

    def test_list_words_pagination(self, app, test_db, monkeypatch):
        conn = sqlite3.connect(test_db)
        for i in range(10):
            _insert_word(conn, f"v{i}", f"word{i}")
        conn.commit()
        conn.close()
        _patch_db(app, test_db, monkeypatch)
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.get("/api/words?page=1&page_size=3")
        body = resp.json()
        assert body["data"]["total"] == 10
        assert len(body["data"]["items"]) == 3

    def test_list_words_search(self, app, test_db, monkeypatch):
        conn = sqlite3.connect(test_db)
        _insert_word(conn, "v1", "abandon")
        _insert_word(conn, "v2", "abstract")
        _insert_word(conn, "v3", "bizarre")
        conn.commit()
        conn.close()
        _patch_db(app, test_db, monkeypatch)
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.get("/api/words?search=ab")
        body = resp.json()
        assert body["data"]["total"] == 2

    def test_list_words_filter_sync_status(self, app, test_db, monkeypatch):
        conn = sqlite3.connect(test_db)
        _insert_word(conn, "v1", "a", sync_status=0)
        _insert_word(conn, "v2", "b", sync_status=2)
        conn.commit()
        conn.close()
        _patch_db(app, test_db, monkeypatch)
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.get("/api/words?sync_status=2")
        body = resp.json()
        assert body["data"]["total"] == 1


class TestWordDetail:
    def test_get_word_not_found(self, app, test_db, monkeypatch):
        monkeypatch.setattr("database.momo_words.get_local_word_note", lambda voc_id: None)
        app.include_router(words_router)
        app.dependency_overrides[deps.get_active_user] = lambda: "testuser"
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/words/nonexistent")
        assert resp.status_code == 404

    def test_get_word_detail_found(self, app, test_db, monkeypatch):
        fake_note = {"voc_id":"v1","spelling":"abandon","basic_meanings":"v. abandon","memory_aid":"a band on","ielts_focus":"high","collocations":"abandon hope","traps":"","synonyms":"desert","discrimination":"","example_sentences":"He abandoned ship.","word_ratings":"4","raw_full_text":"","it_history":"","tags":""}
        monkeypatch.setattr("database.momo_words.get_local_word_note", lambda voc_id: fake_note)
        app.include_router(words_router)
        app.dependency_overrides[deps.get_active_user] = lambda: "testuser"
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/words/v1")
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["spelling"] == "abandon"


class TestWordUpdate:
    def test_update_word_success(self, app, test_db, monkeypatch):
        monkeypatch.setattr(db_conn, "_queue_write_operation", lambda *a, **kw: True)
        monkeypatch.setattr("database.utils.get_timestamp_with_tz", lambda: "2026-01-01T00:00:00")
        app.include_router(words_router)
        app.dependency_overrides[deps.get_active_user] = lambda: "testuser"
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.put("/api/words/v1", json={"memory_aid": "new mnemonic"})
        body = resp.json()
        assert body["ok"] is True

    def test_update_word_empty_memory_aid(self, app, test_db, monkeypatch):
        app.include_router(words_router)
        app.dependency_overrides[deps.get_active_user] = lambda: "testuser"
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.put("/api/words/v1", json={"memory_aid": ""})
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "INVALID_INPUT"


class TestWordIterations:
    def test_iterations_empty(self, app, test_db, monkeypatch):
        _patch_db(app, test_db, monkeypatch)
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.get("/api/words/v1/iterations")
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["iterations"] == []

    def test_iterations_with_data(self, app, test_db, monkeypatch):
        conn = sqlite3.connect(test_db)
        _insert_word(conn, "v1", "abandon")
        conn.execute(
            "INSERT INTO ai_word_iterations "
            "(voc_id, spelling, stage, score, justification, refined_content, raw_response, tags, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
            ("v1", "abandon", "draft", 0.8, "good draft", "{}", "{}", ""),
        )
        conn.execute(
            "INSERT INTO ai_word_iterations "
            "(voc_id, spelling, stage, score, justification, refined_content, raw_response, tags, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
            ("v1", "abandon", "refine", 0.95, "excellent", "{}", "{}", ""),
        )
        conn.commit()
        conn.close()
        _patch_db(app, test_db, monkeypatch)
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.get("/api/words/v1/iterations")
        body = resp.json()
        assert len(body["data"]["iterations"]) == 2
