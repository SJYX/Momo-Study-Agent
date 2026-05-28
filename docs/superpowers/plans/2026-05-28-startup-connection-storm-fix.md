# Startup Connection Storm Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate redundant startup `turso.sync.connect()` calls without reintroducing startup blocking, cross-thread connection sharing, or wrong-DB writes.

**Architecture:** Keep `init_db()` on the current fast path: foreground schema initialization remains local/fast, and cross-device freshness remains outside the SyncGate critical path. Reduce the read-path connection storm by reusing pyturso read connections safely through a managed read-connection lease layer rather than returning one global raw connection. The pool must be keyed by normalized `db_path` and isolated per thread, because pyturso MVCC supports multiple concurrent connections to the same DB file, not necessarily concurrent use of the same connection object.

**Tech Stack:** Python 3.12, pyturso (`turso.sync`), SQLite/libSQL, threading, pytest

---

## Non-Goals

- Do not solve the underlying `urllib.request.urlopen()` socket timeout issue in pyturso internals.
- Do not move `push()`/`pull()` back into the `init_db()` foreground critical path.
- Do not change public DB APIs unless required for safe connection lifecycle handling.
- Do not change Hub connection behavior in this plan; this plan targets main DB startup/read storm only.

---

## Root Cause Summary

During warm-DB web startup, the current connection storm is mainly caused by `_get_local_read_conn()` creating a fresh pyturso connection for every read. Each `turso.sync.connect()` still performs sync-engine bootstrap work even when the local `.db` already exists.

Current relevant paths:

| Source | Current path | Problem |
|---|---|---|
| `init_db` | `_get_local_conn(path)` | One foreground pyturso connection for schema checks; keep fast path unless separately redesigned |
| `_kick_async_pull` | `connect(do_sync=False, do_pull=True)` in daemon thread | Extra connection, but intentionally outside SyncGate; keep behavior unless later freshness strategy changes |
| Read APIs | `_get_read_conn()` -> `_get_local_read_conn()` | Biggest storm source; every read creates a new pyturso connection |
| `with_read_session` | closes `c` in `finally` | Breaks naive pooling if pooled raw connection is returned |
| Direct read callers | call `conn.close()` manually | Also breaks naive pooling |

Important distinction: pyturso MVCC makes **multiple connections** to the same DB safe. It does not prove one shared connection object is safe for simultaneous use by multiple request threads.

---

## Design Decisions

1. **Read pooling must not return a globally shared raw connection.**
   Use a managed lease/wrapper or thread-local cache. Existing callers may call `close()`, so `close()` must release the lease without closing the underlying pooled connection.

2. **Pool isolation is per normalized `db_path` and per thread.**
   This avoids cross-thread use of the same connection object while still eliminating repeated pyturso bootstraps within a request worker thread.

3. **Schema-change recovery invalidates pooled handles.**
   On `"schema changed"` errors, invalidate the current path's read connection(s), then retry once with a fresh connection.

4. **`init_db(db_path)` semantics must be preserved.**
   Do not replace `connection._get_local_conn(path)` with `_get_main_write_conn_singleton(do_sync=True)` in this plan. The current write singleton does not accept `db_path` and internally reads `config.DB_PATH`; using it here risks touching the wrong database when callers pass an explicit path.

5. **Existing async pull tests must be updated only if behavior is intentionally changed.**
   This plan keeps `_kick_async_pull()` as the non-blocking freshness primer, so existing tests around async pull should remain valid or be made stricter, not removed.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `database/connection/factory.py` | Modify `_get_local_read_conn`; add read lease, thread-local pool, invalidation, shutdown cleanup | Safe read connection reuse |
| `database/connection/__init__.py` | Export cleanup/invalidation helpers if needed by other modules/tests | Compatibility re-export |
| `database/session.py` | Add schema-changed retry; do not close underlying pooled connection through raw close semantics | Decorated read recovery |
| `database/execution_engine.py` | Close read pool during DB cleanup/recovery handle release | Shutdown/recovery lifecycle |
| `tests/unit/database/test_connection_storm.py` | Create focused pooling/lifecycle/concurrency tests | Regression coverage |
| `tests/unit/database/test_init_db_async_pull.py` | Keep/update assertions for non-blocking async pull behavior | Guard against startup blocking regression |

---

## Task 1: Safe Read Connection Lease and Thread-Local Pool

**Files:**
- Modify: `database/connection/factory.py`
- Modify: `database/connection/__init__.py`
- Test: `tests/unit/database/test_connection_storm.py`

- [ ] **Step 1: Add failing tests for read reuse and close semantics**

Create `tests/unit/database/test_connection_storm.py`:

```python
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
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
python -m pytest tests/unit/database/test_connection_storm.py -v --tb=short
```

Expected before implementation: failures because `_close_read_conn_pool` does not exist and `_get_local_read_conn()` returns raw connections.

- [ ] **Step 3: Implement a lease wrapper and thread-local read pool**

In `database/connection/factory.py`, add imports:

```python
import threading
```

After existing imports/context setup, add:

```python
_read_conn_pool_lock = threading.Lock()
_read_conn_pool_tls = threading.local()


def _normalize_db_path(db_path: str) -> str:
    return os.path.abspath(db_path)


class _ReadConnectionLease:
    """Lightweight proxy: close() releases the lease, pool cleanup closes raw conn."""

    def __init__(self, raw_conn: Any, db_path: str):
        self._raw_conn = raw_conn
        self._db_path = db_path
        self._closed = False

    @property
    def raw_connection(self) -> Any:
        return self._raw_conn

    def close(self) -> None:
        self._closed = True

    def __enter__(self) -> "_ReadConnectionLease":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __getattr__(self, name: str) -> Any:
        if self._closed:
            self._closed = False
        return getattr(self._raw_conn, name)


def _get_thread_read_pool() -> dict[str, Any]:
    pool = getattr(_read_conn_pool_tls, "pool", None)
    if pool is None:
        pool = {}
        _read_conn_pool_tls.pool = pool
    return pool


def _close_raw_conn(conn: Any) -> None:
    try:
        conn.close()
    except Exception:
        pass
```

Replace `_get_local_read_conn()` pyturso branch with:

```python
    ctx = _resolve_conn_context(path)
    if (HAS_PYTURSO) and ctx.get("url") and ctx.get("token"):
        normalized_path = _normalize_db_path(path)
        pool = _get_thread_read_pool()
        raw_conn = pool.get(normalized_path)

        if raw_conn is not None:
            try:
                raw_conn.execute("SELECT 1")
                return _ReadConnectionLease(raw_conn, normalized_path)
            except Exception:
                _debug_log(
                    f"读连接池失效，重建: {normalized_path}",
                    level="WARNING",
                    module="database.connection.factory",
                )
                pool.pop(normalized_path, None)
                _close_raw_conn(raw_conn)

        raw_conn = _get_backend().connect(path, ctx["url"], ctx["token"], do_sync=False, do_pull=False)
        try:
            raw_conn.execute("PRAGMA query_only=ON;")
        except Exception:
            pass
        pool[normalized_path] = raw_conn
        return _ReadConnectionLease(raw_conn, normalized_path)
```

Keep the non-pyturso sqlite3 branch unchanged and returning a normal sqlite3 connection.

- [ ] **Step 4: Add invalidation and shutdown helpers**

In `database/connection/factory.py`, add:

```python
def _invalidate_read_conn_pool(db_path: str) -> None:
    """Invalidate this thread's pooled read connection for db_path."""
    normalized_path = _normalize_db_path(db_path)
    pool = _get_thread_read_pool()
    raw_conn = pool.pop(normalized_path, None)
    if raw_conn is not None:
        _close_raw_conn(raw_conn)


def _close_read_conn_pool() -> None:
    """Close this thread's pooled read connections."""
    pool = _get_thread_read_pool()
    conns = list(pool.values())
    pool.clear()
    for conn in conns:
        _close_raw_conn(conn)
```

In `database/connection/__init__.py`, export:

```python
    _close_read_conn_pool,
    _invalidate_read_conn_pool,
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
python -m pytest tests/unit/database/test_connection_storm.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 6: Run existing read-connection tests**

Run:

```bash
python -m pytest tests/unit/database/test_read_conn_isolation.py -v --tb=short
```

Expected: PASS. If a test asserts raw connection identity in pyturso mode, update it to assert the lease delegates to the mocked raw connection and that `close()` does not close the raw connection.

- [ ] **Step 7: Commit Task 1**

```bash
git add database/connection/factory.py database/connection/__init__.py tests/unit/database/test_connection_storm.py tests/unit/database/test_read_conn_isolation.py
git commit -m "perf(db): reuse read connections with safe leases"
```

---

## Task 2: Schema-Changed Retry and Cleanup Integration

**Files:**
- Modify: `database/session.py`
- Modify: `database/execution_engine.py`
- Modify: `tests/unit/database/test_connection_storm.py`

- [ ] **Step 1: Add failing test for schema-changed retry**

Append to `tests/unit/database/test_connection_storm.py`:

```python
def test_with_read_session_invalidates_pool_on_schema_changed(monkeypatch, tmp_path):
    from database.connection import factory
    from database.session import DBSession, with_read_session

    first = MagicMock()
    second = MagicMock()
    first.execute.side_effect = RuntimeError("database schema changed")
    factory, db_path, call_count = _enable_fake_pyturso(monkeypatch, tmp_path, [first, second])

    attempts = {"value": 0}

    @with_read_session(default_return="fallback")
    def load_value(session: DBSession = None, db_path: str = None):
        attempts["value"] += 1
        session.execute("SELECT 1")
        return "ok"

    result = load_value(db_path=db_path)

    assert result == "ok"
    assert attempts["value"] == 2
    assert call_count["value"] == 2
    first.close.assert_called_once()
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
python -m pytest tests/unit/database/test_connection_storm.py::test_with_read_session_invalidates_pool_on_schema_changed -v --tb=short
```

Expected before implementation: returns fallback or does not invalidate/retry.

- [ ] **Step 3: Add schema-changed retry before corruption fallback**

In `database/session.py`, inside `with_read_session.wrapper`, add this branch at the start of the `except Exception as e:` block, before corruption handling:

```python
                if "schema changed" in str(e).lower() and not _recovery_attempted:
                    _debug_log(
                        f"{func.__name__} 检测到 schema 变更，重建读连接后重试",
                        level="WARNING",
                        module=func.__module__,
                    )
                    try:
                        from database.connection import _invalidate_read_conn_pool
                        _invalidate_read_conn_pool(db_path)
                    except Exception:
                        try:
                            if c is not None:
                                c.close()
                        except Exception:
                            pass
                    kwargs.pop("session", None)
                    kwargs["_recovery_attempted"] = True
                    return wrapper(*args, **kwargs)
```

Do not add unconditional raw close logic that would close healthy pooled connections. The lease `close()` in `finally` should release only the lease.

- [ ] **Step 4: Close read pools during DB cleanup**

In `database/execution_engine.py`, update imports:

```python
from database.connection import (
    _get_dedicated_write_conn,
    _close_main_write_conn_singleton,
    _close_hub_write_conn_singleton,
    _close_read_conn_pool,
    _is_main_db_path,
    _get_local_conn,
    HUB_DB_PATH,
)
```

Update `cleanup_db_session_resources()`:

```python
def cleanup_db_session_resources() -> None:
    """DB session 资源清理：关闭主库、Hub 写连接 singleton 与当前线程读连接池。"""
    _close_read_conn_pool()
    _close_main_write_conn_singleton()
    _close_hub_write_conn_singleton()
    _debug_log("DB session 资源清理完成", level="INFO")
```

Update `_release_db_file_handles_for_recovery(db_path)` to invalidate read pool for the target DB before recovery:

```python
        from database.connection import _invalidate_read_conn_pool
        _invalidate_read_conn_pool(abs_path)
```

Place it before closing write singletons.

- [ ] **Step 5: Run focused tests**

Run:

```bash
python -m pytest tests/unit/database/test_connection_storm.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 6: Run database unit tests**

Run:

```bash
python -m pytest tests/unit/database/ -v --tb=short -m "not slow"
```

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add database/session.py database/execution_engine.py tests/unit/database/test_connection_storm.py
git commit -m "fix(db): refresh pooled read connection on schema changes"
```

---

## Task 3: Preserve Startup Fast Path and Async Pull Contract

**Files:**
- Modify: `tests/unit/database/test_init_db_async_pull.py` only if assertions need tightening
- Do not modify: `database/schema.py` unless a test reveals a real regression

- [ ] **Step 1: Confirm `init_db` still avoids write singleton foreground sync**

Run:

```bash
python -m pytest tests/unit/database/test_init_db_async_pull.py -v --tb=short
```

Expected: PASS. The cloud path should still call `_kick_async_pull(path)` once and `_kick_async_pull()` should return immediately.

- [ ] **Step 2: Add a guard test if missing**

If the existing tests do not catch foreground singleton usage, add this test to `tests/unit/database/test_init_db_async_pull.py`:

```python
@pytest.mark.unit
def test_init_db_cloud_path_does_not_use_write_singleton(tmp_path, monkeypatch):
    monkeypatch.setenv("TURSO_DB_URL", "libsql://fake.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "fake-token")
    monkeypatch.delenv("TURSO_HUB_DB_URL", raising=False)
    monkeypatch.delenv("TURSO_HUB_AUTH_TOKEN", raising=False)

    import database.schema
    import database.connection.singleton as conn_singleton
    import database.connection.context as conn_context
    import sqlite3

    class _StubBackend:
        name = "pyturso"

        def connect(self, db_path, url, token, *, do_sync=False, do_pull=True):
            c = sqlite3.connect(db_path, timeout=5.0)
            c.execute("PRAGMA journal_mode=WAL;")
            return c

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
```

- [ ] **Step 3: Run startup fast-path tests**

Run:

```bash
python -m pytest tests/unit/database/test_init_db_async_pull.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 4: Commit Task 3 if tests changed**

```bash
git add tests/unit/database/test_init_db_async_pull.py
git commit -m "test(db): guard init_db fast startup path"
```

If no test changes were needed, skip commit.

---

## Task 4: Integration Verification for Startup Connection Count

**Files:**
- Modify: `tests/unit/database/test_connection_storm.py`

- [ ] **Step 1: Add an integration-style startup read burst test**

Append to `tests/unit/database/test_connection_storm.py`:

```python
def test_read_burst_uses_one_pyturso_connect_per_thread(monkeypatch, tmp_path):
    from database.connection import factory

    raw_conn = MagicMock()
    factory, db_path, call_count = _enable_fake_pyturso(monkeypatch, tmp_path, [raw_conn])

    for _ in range(10):
        conn = factory._get_read_conn(db_path)
        conn.execute("SELECT 1")
        conn.close()

    assert call_count["value"] == 1
```

- [ ] **Step 2: Add a multi-thread isolation test**

Append:

```python
def test_read_pool_does_not_share_raw_connection_across_threads(monkeypatch, tmp_path):
    import threading
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
```

- [ ] **Step 3: Run connection storm tests**

Run:

```bash
python -m pytest tests/unit/database/test_connection_storm.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 4: Run broader verification**

Run:

```bash
python -m pytest tests/unit/database/ -v --tb=short -m "not slow"
python -m pytest tests/web/ -v --tb=short -m "not slow"
```

Expected: PASS.

- [ ] **Step 5: Manual startup smoke test**

Run:

```bash
python scripts/start_web.py --dev
```

Expected manual observations:

- Startup does not wait for foreground `push()`/`pull()` beyond existing `init_db` behavior.
- During a same-thread startup read burst, repeated read APIs do not emit a new `[主库] turso.sync.connect 完成` log for every read.
- `_kick_async_pull` remains non-blocking.
- Read APIs still work, for example `/api/users/asher/words` and `/api/stats/...`.

- [ ] **Step 6: Commit Task 4**

```bash
git add tests/unit/database/test_connection_storm.py
git commit -m "test(db): verify bounded read connection startup behavior"
```

---

## Expected Impact

| Metric | Before | After |
|---|---|---|
| Read connections per repeated same-thread API burst | 1 new pyturso connection per read | 1 pyturso connection reused by lease |
| Cross-thread raw connection sharing | Not applicable | Avoided by thread-local pool |
| Caller `close()` behavior | Closes raw read connection | Releases lease only for pyturso pooled reads |
| Schema-changed pooled read | Falls through to default error path | Invalidates pool and retries once |
| `init_db(db_path)` explicit path semantics | Preserved | Preserved |
| Startup foreground sync behavior | Fast path + async pull | Preserved |

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| A caller depends on `isinstance(conn, sqlite3.Connection)` in pyturso mode | Pyturso mode already returns pyturso connections, not sqlite3. Lease delegates through `__getattr__`; update only tests that over-specify raw identity. |
| Thread-local pools are not globally closed on shutdown for inactive worker threads | This is acceptable for process shutdown; current cleanup closes current thread handles. If long-lived worker churn becomes visible later, add a bounded checkout pool with explicit global registry. |
| Schema changes in another thread do not invalidate that thread's pool | The first query in each thread will detect `"schema changed"` and invalidate its own pool. |
| Direct code accesses private `raw_connection` | `raw_connection` exists only for tests and debugging. Production code should treat the lease as a DB connection. |

---

## Final Verification

Run:

```bash
python -m pytest tests/unit/database/test_connection_storm.py -v --tb=short
python -m pytest tests/unit/database/test_init_db_async_pull.py -v --tb=short
python -m pytest tests/unit/database/ -v --tb=short -m "not slow"
python -m pytest tests/web/ -v --tb=short -m "not slow"
```

Manual smoke:

```bash
python scripts/start_web.py --dev
```

Completion criteria:

- Focused tests pass.
- Existing database unit tests pass.
- Existing web tests pass or unrelated failures are documented with exact failure output.
- Manual startup confirms read bursts do not create one pyturso connection per read.
- No foreground `init_db` change introduces a blocking push/pull dependency.

