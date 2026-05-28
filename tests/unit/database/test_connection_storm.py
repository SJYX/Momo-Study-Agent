from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def clear_read_pool():
    from database.connection import factory

    if hasattr(factory, "_close_read_conn_pool"):
        factory._close_read_conn_pool()
    yield
    if hasattr(factory, "_close_read_conn_pool"):
        factory._close_read_conn_pool()


def _enable_fake_pyturso(monkeypatch, tmp_path, conns):
    from database.connection import factory

    db_path = str(tmp_path / "main.db")
    call_count = {"value": 0}
    call_lock = threading.Lock()

    def fake_connect(path, url, token, **kwargs):
        assert path == db_path
        with call_lock:
            idx = min(call_count["value"], len(conns) - 1)
            call_count["value"] += 1
        return conns[idx]

    fake_backend = MagicMock()
    fake_backend.name = "pyturso"
    fake_backend.connect = fake_connect

    fake_ctx = {
        "db_path": db_path,
        "is_main_db": True,
        "is_test": False,
        "url": "libsql://fake.turso.io",
        "token": "fake-token",
        "force_cloud_mode": False,
    }

    monkeypatch.setattr(factory, "HAS_PYTURSO", True)
    monkeypatch.setattr(factory, "_resolve_conn_context", lambda *a, **k: fake_ctx)
    monkeypatch.setattr(factory, "_get_backend", lambda: fake_backend)
    monkeypatch.setattr(factory, "_should_use_local_only_connection", lambda *a, **k: False)
    return factory, db_path, call_count


def test_read_conn_reused_after_caller_close(monkeypatch, tmp_path):
    """Caller close() must release the lease, not close the pooled raw connection."""
    raw_conn = MagicMock()
    factory, db_path, call_count = _enable_fake_pyturso(monkeypatch, tmp_path, [raw_conn])

    conn1 = factory._get_local_read_conn(db_path)
    conn1.execute("SELECT 1")
    conn1.close()

    conn2 = factory._get_local_read_conn(db_path)
    conn2.execute("SELECT 1")
    conn2.close()

    assert call_count["value"] == 1
    raw_conn.close.assert_not_called()


def test_broken_pooled_read_conn_is_recreated(monkeypatch, tmp_path):
    first = MagicMock()
    second = MagicMock()
    first.execute.side_effect = RuntimeError("connection closed")
    factory, db_path, call_count = _enable_fake_pyturso(monkeypatch, tmp_path, [first, second])

    conn1 = factory._get_local_read_conn(db_path)
    conn1.close()

    conn2 = factory._get_local_read_conn(db_path)
    conn2.execute("SELECT 1")
    conn2.close()

    assert call_count["value"] == 2
    first.close.assert_called_once()
    second.close.assert_not_called()


def test_close_read_conn_pool_closes_underlying_connections(monkeypatch, tmp_path):
    raw_conn = MagicMock()
    factory, db_path, _ = _enable_fake_pyturso(monkeypatch, tmp_path, [raw_conn])

    lease = factory._get_local_read_conn(db_path)
    lease.close()

    factory._close_read_conn_pool()

    raw_conn.close.assert_called_once()


def test_with_read_session_invalidates_pool_on_schema_changed(monkeypatch, tmp_path):
    from database.connection import factory
    from database.session import DBSession, with_read_session

    first = MagicMock()
    second = MagicMock()
    # Health check passes (SELECT 1), but cursor().execute() in DBSession fails
    _orig_cursor = first.cursor

    def _bad_cursor():
        cur = _orig_cursor()
        _orig_cur_exec = cur.execute

        def _cur_exec(sql, *a, **kw):
            if sql == "SELECT 1":
                return _orig_cur_exec(sql, *a, **kw)
            raise RuntimeError("database schema changed")

        cur.execute = _cur_exec
        return cur

    first.cursor = _bad_cursor
    factory, db_path, call_count = _enable_fake_pyturso(monkeypatch, tmp_path, [first, second])

    attempts = {"value": 0}

    @with_read_session(default_return="fallback")
    def load_value(session: DBSession = None, db_path: str = None):
        attempts["value"] += 1
        session.execute("SELECT 42")
        return "ok"

    result = load_value(db_path=db_path)

    assert result == "ok"
    assert attempts["value"] == 2
    assert call_count["value"] == 2
    first.close.assert_called_once()


def test_read_burst_uses_one_pyturso_connect_per_thread(monkeypatch, tmp_path):
    from database.connection import factory

    raw_conn = MagicMock()
    factory, db_path, call_count = _enable_fake_pyturso(monkeypatch, tmp_path, [raw_conn])

    for _ in range(10):
        conn = factory._get_read_conn(db_path)
        conn.execute("SELECT 1")
        conn.close()

    assert call_count["value"] == 1


def test_read_pool_does_not_share_raw_connection_across_threads(monkeypatch, tmp_path):
    from database.connection import factory

    raw_conns = [MagicMock(), MagicMock()]
    factory, db_path, call_count = _enable_fake_pyturso(monkeypatch, tmp_path, raw_conns)

    barrier = threading.Barrier(2)
    results = []

    def worker():
        barrier.wait(timeout=5)
        conn = factory._get_read_conn(db_path)
        conn.execute("SELECT 1")
        results.append(conn.raw_connection)
        conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(results) == 2
    assert results[0] is not results[1]
    assert call_count["value"] == 2
