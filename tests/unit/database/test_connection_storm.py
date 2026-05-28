from __future__ import annotations

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

    def fake_connect(path, url, token, **kwargs):
        assert path == db_path
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
