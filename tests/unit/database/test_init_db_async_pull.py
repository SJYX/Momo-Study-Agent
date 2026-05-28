"""tests/unit/database/test_init_db_async_pull.py: Fix D — verify init_db
goes through the local-fast path and kicks a background pyturso pull
when cloud config is present.

Two behaviors covered:

  1. init_db calls _kick_async_pull(path) exactly once when TURSO_DB_URL
     is configured — that's the cross-device freshness primer.
  2. _kick_async_pull itself returns essentially instantly (just spawns
     a daemon thread; the actual pull runs in the background).
"""
from __future__ import annotations

import sqlite3
import threading
import time

import pytest


@pytest.mark.unit
def test_kick_async_pull_returns_immediately():
    """_kick_async_pull must be non-blocking — it only spawns a thread."""
    import database.schema

    started_at = time.time()
    # Pass a bogus path; the inner thread will error harmlessly because no
    # cloud env / no backend is set up — but the OUTER call must return now.
    database.schema._kick_async_pull("/tmp/nonexistent.db")
    elapsed = time.time() - started_at

    assert elapsed < 0.2, (
        f"_kick_async_pull took {elapsed:.3f}s; expected near-instant spawn"
    )


@pytest.mark.unit
def test_init_db_cloud_path_kicks_async_pull(tmp_path, monkeypatch):
    """When TURSO_DB_URL is set, init_db must call _kick_async_pull(path) so
    cross-device users get fresh data shortly after SyncGate dismisses.

    Backing assumption: init_db itself no longer does push/pull on the
    critical path (Fix D). Pull is handed to a background thread.
    """
    # Cloud env triggers the is_cloud branch in init_db
    monkeypatch.setenv("TURSO_DB_URL", "libsql://fake.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "fake-token")
    monkeypatch.delenv("TURSO_HUB_DB_URL", raising=False)
    monkeypatch.delenv("TURSO_HUB_AUTH_TOKEN", raising=False)

    # Stub the pyturso backend so the foreground _get_local_conn doesn't
    # try to reach the fake cloud URL. We return a real sqlite3 connection
    # because init_db will run CREATE TABLE IF NOT EXISTS / apply_migrations
    # on it; sqlite3 satisfies all those calls.
    import database.connection.context as conn_context

    class _StubBackend:
        name = "pyturso"

        def connect(self, db_path, url, token, *, do_sync=False, do_pull=True):
            c = sqlite3.connect(db_path, timeout=5.0)
            c.execute("PRAGMA journal_mode=WAL;")
            c.execute("PRAGMA busy_timeout=5000;")
            return c

        def do_sync_on(self, conn):
            pass

    monkeypatch.setattr(conn_context, "_backend", _StubBackend())

    # Pre-seed user_version so apply_migrations sees no work to do
    # (V001-V007 have already been "applied" from the local SQLite POV).
    db_path = str(tmp_path / "test.db")
    seed = sqlite3.connect(db_path)
    seed.execute("PRAGMA user_version = 7;")
    seed.commit()
    seed.close()

    # Record _kick_async_pull calls and replace with no-op so we don't
    # actually spawn the thread (we're testing the call, not the thread body).
    import database.schema

    pull_calls: list[str] = []
    monkeypatch.setattr(database.schema, "_kick_async_pull", lambda p: pull_calls.append(p))
    # Hub init is independent; stub to no-op.
    monkeypatch.setattr(database.schema, "init_users_hub_tables", lambda: True)

    database.schema.init_db(db_path)

    assert pull_calls == [db_path], (
        f"Expected _kick_async_pull called once with {db_path!r}, got {pull_calls!r}"
    )


@pytest.mark.unit
def test_init_db_local_only_does_not_kick_async_pull(tmp_path, monkeypatch):
    """No cloud config → no async pull thread (no remote to pull from)."""
    monkeypatch.delenv("TURSO_DB_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TURSO_DB_HOSTNAME", raising=False)

    import database.schema

    pull_calls: list[str] = []
    monkeypatch.setattr(database.schema, "_kick_async_pull", lambda p: pull_calls.append(p))
    monkeypatch.setattr(database.schema, "init_users_hub_tables", lambda: True)

    db_path = str(tmp_path / "test.db")
    database.schema.init_db(db_path)

    assert pull_calls == [], (
        f"local-only init_db should not call _kick_async_pull, but got {pull_calls!r}"
    )


@pytest.mark.unit
def test_init_db_cloud_path_does_not_use_write_singleton(tmp_path, monkeypatch):
    monkeypatch.setenv("TURSO_DB_URL", "libsql://fake.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "fake-token")
    monkeypatch.delenv("TURSO_HUB_DB_URL", raising=False)
    monkeypatch.delenv("TURSO_HUB_AUTH_TOKEN", raising=False)

    import database.schema
    import database.connection.singleton as conn_singleton
    import database.connection.context as conn_context

    class _StubBackend:
        name = "pyturso"

        def connect(self, db_path, url, token, *, do_sync=False, do_pull=True):
            c = sqlite3.connect(db_path, timeout=5.0)
            c.execute("PRAGMA journal_mode=WAL;")
            return c

        def do_sync_on(self, conn):
            pass

    monkeypatch.setattr(conn_context, "_backend", _StubBackend())
    monkeypatch.setattr(database.schema, "_kick_async_pull", lambda p: None)
    monkeypatch.setattr(database.schema, "init_users_hub_tables", lambda: True)

    called = {"value": False}

    def fail_if_called(*args, **kwargs):
        called["value"] = True
        raise AssertionError("init_db must not call write singleton on foreground path")

    monkeypatch.setattr(conn_singleton, "_get_main_write_conn_singleton", fail_if_called)

    database.schema.init_db(str(tmp_path / "test.db"))

    assert called["value"] is False
