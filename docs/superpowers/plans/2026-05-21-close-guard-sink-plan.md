# Close-Guard Sink to Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all `_is_main_write_singleton_conn(conn)` / `_is_hub_write_singleton_conn(conn)` close-guard logic into Backend via `should_close(conn)`, then delete the two helper functions.

**Architecture:** Each Backend tracks singleton connections via `self._singleton_ids: set[int]` (using `id()` to avoid `AttributeError` on C/Rust extension objects). `connect()` gains `is_singleton=False` keyword parameter. `should_close(conn)` returns `id(conn) not in self._singleton_ids`.

**Tech Stack:** Python, TursoBackend Protocol, pytest

---

## File Map

| File | Role |
|------|------|
| `database/backends/_protocol.py` | Add `should_close` + `is_singleton` to Protocol |
| `database/backends/_libsql.py` | Add `_singleton_ids`, `should_close`, `is_singleton` on `connect()` |
| `database/backends/_pyturso.py` | Same as _libsql |
| `database/connection.py` | Pass `is_singleton=True` at 2 creation sites; delete 2 functions; update 3 call sites |
| `database/session.py` | 4 call sites → `backend.should_close(c)` |
| `database/execution_engine.py` | 1 call site + delete import |
| `database/community_lookup.py` | 1 call site |
| `database/notes_repo.py` | 2 call sites + delete import |
| `database/momo_words.py` | 1 call site |
| `database/schema.py` | 2 call sites |
| `core/iteration_manager.py` | 2 call sites + delete import |
| `core/weak_word_filter.py` | 1 call site + delete import |
| `web/backend/routers/stats.py` | 3 call sites + delete import |
| `web/backend/routers/ops.py` | 1 call site + delete import |
| 6 test files | Update mocks |

---

### Task 1: Protocol + Both Backends — Add `should_close` and `is_singleton`

**Files:**
- Modify: `database/backends/_protocol.py`
- Modify: `database/backends/_libsql.py`
- Modify: `database/backends/_pyturso.py`

- [ ] **Step 1a: Add `should_close` and `is_singleton` to Protocol**

```python
# database/backends/_protocol.py
@runtime_checkable
class TursoBackend(Protocol):
    name: str

    @contextmanager
    def op_lock_for(self, conn: Any) -> Iterator[None]: ...

    def should_close(self, conn: Any) -> bool: ...  # NEW

    def connect(
        self, db_path: str, url: str, token: str,
        *, do_sync: bool = False, is_singleton: bool = False,  # is_singleton NEW
    ) -> Any: ...

    def do_sync_on(self, conn: Any) -> None: ...
    def is_supported(self) -> bool: ...
```

- [ ] **Step 1b: Add `_singleton_ids` + `should_close` to PytursoBackend**

```python
# database/backends/_pyturso.py — in __init__ (add class + init)
class PytursoBackend:
    name = "pyturso"

    def __init__(self):                          # NEW
        self._singleton_ids: set[int] = set()    # NEW

    @contextmanager
    def op_lock_for(self, conn: Any) -> Iterator[None]:
        yield

    def should_close(self, conn: Any) -> bool:           # NEW
        return id(conn) not in self._singleton_ids        # NEW

    def connect(self, db_path, url, token, *, do_sync=False, is_singleton=False):
        db = turso.sync.connect(...)
        if is_singleton:
            self._singleton_ids.add(id(db))
        # ... existing body ...
        return db
```

- [ ] **Step 1c: Add `_singleton_ids` + `should_close` to LibsqlBackend**

```python
# database/backends/_libsql.py — in __init__ (add to existing)
class LibsqlBackend:
    name = "libsql"

    def __init__(self):
        self._singleton_ids: set[int] = set()    # NEW
        self._main_lock = threading.Lock()
        self._hub_lock = threading.Lock()

    def should_close(self, conn: Any) -> bool:           # NEW
        return id(conn) not in self._singleton_ids        # NEW

    def connect(self, db_path, url, token, *, do_sync=False, is_singleton=False):
        conn = libsql.connect(...)
        if is_singleton:
            self._singleton_ids.add(id(conn))
        # ... existing body ...
        return conn
```

- [ ] **Step 1d: Run existing tests to verify no regressions**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
```

- [ ] **Step 1e: Commit**

```bash
git add database/backends/
git commit -m "feat(backend): add should_close() + is_singleton to Protocol and both backends"
```

---

### Task 2: Pass `is_singleton=True` in Singleton Creation

**Files:**
- Modify: `database/connection.py` lines 449, 514

- [ ] **Step 2a: Main write singleton creation (~line 449)**

```python
# Before:
conn = _get_backend().connect(_config.DB_PATH, ctx["url"], ctx["token"], do_sync=do_sync)
# After:
conn = _get_backend().connect(_config.DB_PATH, ctx["url"], ctx["token"], do_sync=do_sync, is_singleton=True)
```

- [ ] **Step 2b: Hub write singleton creation (~line 514)**

```python
# Before:
conn = _get_backend().connect(HUB_DB_PATH, TURSO_HUB_DB_URL, TURSO_HUB_AUTH_TOKEN, do_sync=do_sync)
# After:
conn = _get_backend().connect(HUB_DB_PATH, TURSO_HUB_DB_URL, TURSO_HUB_AUTH_TOKEN, do_sync=do_sync, is_singleton=True)
```

- [ ] **Step 2c: Run tests**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
```

- [ ] **Step 2d: Commit**

```bash
git add database/connection.py
git commit -m "feat(connection): pass is_singleton=True when creating singleton connections"
```

---

### Task 3: Migrate Call Sites in `database/connection.py` (3 sites)

**Files:**
- Modify: `database/connection.py` lines 746, 784, 824

- [ ] **Step 3a: `_run_with_managed_connection` finally block (~line 746)**

```python
# Before:
if not _is_main_write_singleton_conn(target_conn) and not _is_hub_write_singleton_conn(target_conn):
    target_conn.close()

# After:
from database.backends import get_active_backend
if get_active_backend().should_close(target_conn):
    target_conn.close()
```

- [ ] **Step 3b: `_hub_fetch_one_dict` (~line 784)**

```python
# Before:
is_singleton = _is_hub_write_singleton_conn(hub_conn)
# ... op_lock ...
if not is_singleton:
    hub_conn.close()

# After:
if not get_active_backend().should_close(hub_conn):
    pass  # singleton — skip close
else:
    try:
        hub_conn.close()
    except Exception:
        pass
```

Simpler — replace the whole pattern:
```python
        with _get_backend().op_lock_for(hub_conn):
            cur = hub_conn.cursor()
            try:
                cur.execute(sql, params)
                row = cur.fetchone()
            finally:
                cur.close()
            hub_conn.commit()
        if not _get_backend().should_close(hub_conn):
            pass  # singleton, managed by backend
        else:
            try:
                hub_conn.close()
            except Exception:
                pass
```

Wait — the semantics is: `is_singleton = _is_hub_write_singleton_conn(hub_conn)` → if NOT singleton, close it. That's exactly `should_close()`: returns True means "safe to close". So the simplest replacement:

```python
        if _get_backend().should_close(hub_conn):
            try:
                hub_conn.close()
            except Exception:
                pass
```

- [ ] **Step 3c: `_hub_fetch_all_dicts` (~line 824)** — same pattern as 3b

- [ ] **Step 3d: Run tests + commit**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
git add database/connection.py
git commit -m "refactor(connection): migrate close-guard calls to backend.should_close()"
```

---

### Task 4: Migrate Call Sites in `database/session.py` (4 sites)

**Files:**
- Modify: `database/session.py` lines 96, 161, 183, 225

All 4 sites have `connection._is_main_write_singleton_conn(c)`. In session.py, `DBSession` already has `self._backend`. In `_attempt_auto_recovery`, get backend on the fly.

- [ ] **Step 4a: `_attempt_auto_recovery` (~line 96)**

```python
# Before:
if not connection._is_main_write_singleton_conn(repair_conn):
    repair_conn.close()

# After:
from database.backends import get_active_backend
if get_active_backend().should_close(repair_conn):
    repair_conn.close()
```

- [ ] **Step 4b: `with_read_session` except handler (~line 161)**

```python
# Before:
if c is not None and not connection._is_main_write_singleton_conn(c):
    c.close()

# After:
from database.backends import get_active_backend
if c is not None and get_active_backend().should_close(c):
    c.close()
```

- [ ] **Step 4c: `with_read_session` finally block (~line 183)** — same pattern as 4b

- [ ] **Step 4d: `with_write_session` finally block (~line 225)** — same pattern

Note: `session.py` already imports `from database.backends import get_active_backend` at line 139. Reuse that import rather than adding duplicates. Move the import to module level if needed.

- [ ] **Step 4e: Run tests + commit**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
git add database/session.py
git commit -m "refactor(session): migrate close-guard calls to backend.should_close()"
```

---

### Task 5: Migrate `_mark_main_db_needs_sync` in `execution_engine.py` (1 site)

**Files:**
- Modify: `database/execution_engine.py` lines 21, 426

- [ ] **Step 5a: Change the logic (~line 426)**

```python
# Before:
if not _is_main_write_singleton_conn(conn):
    return

# After:
from database.backends import get_active_backend
if get_active_backend().should_close(conn):
    return
```

Logic check: `_is_main_write_singleton_conn(conn)` returns True if conn IS the singleton. `should_close(conn)` returns True if conn is NOT a singleton. So `not is_singleton` = `should_close`. The replacement `if should_close(conn): return` is semantically identical.

- [ ] **Step 5b: Delete import of `_is_main_write_singleton_conn` (~line 21)**

Remove `_is_main_write_singleton_conn` from the import line. Keep other imports on that line intact.

- [ ] **Step 5c: Run tests + commit**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
git add database/execution_engine.py
git commit -m "refactor(execution_engine): migrate close-guard to backend.should_close()"
```

---

### Task 6: Migrate Remaining Call Sites (7 files, 10 sites)

Group by file for atomic commits.

- [ ] **Step 6a: `database/community_lookup.py` (~line 175)**

```python
# Before: if c is not None and not connection._is_main_write_singleton_conn(c):
# After:  if c is not None and get_active_backend().should_close(c):
```
Add `from database.backends import get_active_backend` import.

- [ ] **Step 6b: `database/notes_repo.py` (~line 481 import, ~line 551 usage)**

```python
# Before: from database.connection import ... _is_main_write_singleton_conn
#         if not _is_main_write_singleton_conn(write_conn):
# After:  from database.backends import get_active_backend
#         if get_active_backend().should_close(write_conn):
```

- [ ] **Step 6c: `database/momo_words.py` (~line 199)**

```python
# Before: if not connection._is_main_write_singleton_conn(c):
# After:  from database.backends import get_active_backend
#         if get_active_backend().should_close(c):
```

- [ ] **Step 6d: `database/schema.py` (lines 393, 454)**

```python
# Before: if not connection._is_hub_write_singleton_conn(hub_conn):
# After:  from database.backends import get_active_backend
#         if get_active_backend().should_close(hub_conn):
```
Both sites have same pattern (close hub_conn if not singleton).

- [ ] **Step 6e: `core/iteration_manager.py` (lines 8 import, 171, 334)**

```python
# Before: from database.connection import ... _is_main_write_singleton_conn
#         if not _is_main_write_singleton_conn(conn):
# After:  from database.backends import get_active_backend
#         if get_active_backend().should_close(conn):
```
Delete `_is_main_write_singleton_conn` from existing import line 8.

- [ ] **Step 6f: `core/weak_word_filter.py` (lines 16 import, 161)**

```python
# Before: from database.connection import ... _is_main_write_singleton_conn
#         if not _is_main_write_singleton_conn(conn):
# After:  from database.backends import get_active_backend
#         if get_active_backend().should_close(conn):
```

- [ ] **Step 6g: `web/backend/routers/stats.py` (lines 32, 69, 98, 114, 134)**

Three functions each import `_is_main_write_singleton_conn` locally. Replace all with `get_active_backend().should_close(conn)`. Delete the old imports.

- [ ] **Step 6h: `web/backend/routers/ops.py` (lines 116, 127)**

```python
# Before: from database.connection import _get_read_conn, _is_main_write_singleton_conn
#         if not _is_main_write_singleton_conn(rconn):
# After:  from database.backends import get_active_backend
#         if get_active_backend().should_close(rconn):
```

- [ ] **Step 6i: Run tests + commit all together**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
git add database/community_lookup.py database/notes_repo.py database/momo_words.py \
      database/schema.py core/iteration_manager.py core/weak_word_filter.py \
      web/backend/routers/stats.py web/backend/routers/ops.py
git commit -m "refactor: migrate remaining close-guard calls to backend.should_close()"
```

---

### Task 7: Delete Dead Code

**Files:**
- Modify: `database/connection.py` lines 268-275

- [ ] **Step 7a: Delete `_is_main_write_singleton_conn` and `_is_hub_write_singleton_conn`**

Remove lines 268-275 from `database/connection.py`:
```python
def _is_main_write_singleton_conn(conn: Any) -> bool:
    with _main_write_conn_lock:
        return conn is not None and conn is _main_write_conn_singleton

def _is_hub_write_singleton_conn(conn: Any) -> bool:
    with _hub_write_conn_lock:
        return conn is not None and conn is _hub_write_conn_singleton
```

- [ ] **Step 7b: Verify no remaining references (should be empty)**

```bash
python -c "
import ast, sys
for f in ['database/session.py','database/connection.py','database/execution_engine.py',
          'database/community_lookup.py','database/notes_repo.py','database/momo_words.py',
          'database/schema.py','core/iteration_manager.py','core/weak_word_filter.py',
          'web/backend/routers/stats.py','web/backend/routers/ops.py']:
    with open(f) as fh:
        if '_is_main_write_singleton_conn' in fh.read():
            print(f'STALE REF in {f}')
            sys.exit(1)
print('OK — no stale references')
"
```

- [ ] **Step 7c: Run tests + commit**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
git add database/connection.py
git commit -m "refactor: delete dead _is_main_write_singleton_conn / _is_hub_write_singleton_conn"
```

---

### Task 8: Update Test Mocks

**Files:**
- Modify: `tests/web/test_words.py` line 20
- Modify: `tests/web/test_sync.py` lines 19, 35, 58, 98, 113
- Modify: `tests/web/test_stats.py` lines 25, 70, 95
- Modify: `tests/core/test_weak_word_filter.py` line 88
- Modify: `tests/unit/database/test_read_conn_isolation.py` lines 54, 71, 203

- [ ] **Step 8a: `tests/web/test_words.py`**

```python
# Before:
monkeypatch.setattr(db_conn, "_is_main_write_singleton_conn", lambda conn: False)
# After:
mock_backend.should_close.return_value = True
```
(Tests already use `mock_backend` — just ensure `should_close` is set. If no mock_backend, create one.)

- [ ] **Step 8b: `tests/web/test_sync.py`** — Same pattern for all 5 sites. All use `monkeypatch.setattr("database.connection._is_main_write_singleton_conn", lambda conn: False)`. Replace with `mock_backend.should_close.return_value = True`.

- [ ] **Step 8c: `tests/web/test_stats.py`** — Same pattern for all 3 sites.

- [ ] **Step 8d: `tests/core/test_weak_word_filter.py`**

```python
# Before:
monkeypatch.setattr(db_connection, "_is_main_write_singleton_conn", lambda conn: False)
# After:
mock_backend.should_close.return_value = True
```

- [ ] **Step 8e: `tests/unit/database/test_read_conn_isolation.py`**

```python
# Before:
assert not conn_mod._is_main_write_singleton_conn(conn)
# After:
assert get_active_backend().should_close(conn)
```
Import `get_active_backend` from `database.backends`.

- [ ] **Step 8f: Run tests + commit**

```bash
python -m pytest tests/ -v --tb=short -m "not slow" -x
git add tests/
git commit -m "test: update mocks from _is_main_write_singleton_conn to backend.should_close"
```

---

### Task 9: Final Verification

- [ ] **Step 9a: Full regression**

```bash
python -m pytest tests/ -v --tb=short -m "not slow"
```

- [ ] **Step 9b: Verify Protocol conformance**

```python
python -c "
from database.backends._pyturso import PytursoBackend
from database.backends._libsql import LibsqlBackend
from database.backends._protocol import TursoBackend
assert isinstance(PytursoBackend(), TursoBackend)
assert isinstance(LibsqlBackend(), TursoBackend)
print('Protocol conformance OK')
"
```

- [ ] **Step 9c: Verify `_singleton_ids` tracking works**

```python
python -c "
from database.backends._pyturso import PytursoBackend
b = PytursoBackend()
class FakeConn: pass
c1 = FakeConn()
c2 = FakeConn()
assert b.should_close(c1) is True  # not registered
b._singleton_ids.add(id(c1))
assert b.should_close(c1) is False  # registered
assert b.should_close(c2) is True   # different conn
print('should_close logic OK')
"
```

- [ ] **Step 9d: Commit**

```bash
git add -A
git commit -m "test: final close-guard sink verification"
```

---

## Risk Notes

1. **`is_singleton=True` must not be missed** at the 2 creation sites in `connection.py`. If missed, the singleton will be incorrectly closed and rebuilt on next use. Silent error — no crash, just performance regression.

2. **Local connections** (`_get_local_conn`, `_get_local_read_conn`) don't go through `backend.connect()`, so they won't be in `_singleton_ids`. `should_close()` correctly returns `True` for them.

3. **`id()` reuse is safe here** because singleton connections live for the entire process lifetime. The `_singleton_ids` set won't have stale entries.

4. **`_main_write_conn_singleton` / `_hub_write_conn_singleton` globals** in `connection.py` remain — they're used by `_get_main_write_conn_singleton()` and `_get_hub_write_conn_singleton()` for assignment/health checks. Only the `_is_*_singleton_conn()` helper functions are deleted.
