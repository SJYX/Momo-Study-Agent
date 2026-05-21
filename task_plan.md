# Task Plan — Embedded Replica Cleanup: Protocol Abstraction Layer

**Goal:** Introduce `TursoBackend` Protocol to replace scattered `hasattr` dispatch, split backend-specific code into `database/backends/`, make pyturso the preferred default. Both backends retained. ~380 lines removed from `connection.py`.

---

## Task 1: Create `database/backends/` package with Protocol

**Files:**
- Create: `database/backends/__init__.py`
- Create: `database/backends/_protocol.py`

**设计原则**：
- `backends/__init__.py` 是 `HAS_LIBSQL`/`HAS_PYTURSO` 的**唯一真相来源**（集中探针）
- 所有外部模块直接 `from database.backends import HAS_LIBSQL, HAS_PYTURSO` — 无懒加载心智负担
- `_libsql.py`/`_pyturso.py` **绝不能**从 `database.connection` 导入（防循环）
- `_libsql.py` 的 `set_db_syncing`/`clear_db_syncing` 使用**函数内懒导入**

- [ ] **Step 1.1: Write `_protocol.py`**

```python
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class TursoBackend(Protocol):
    name: str

    def connect(
        self, db_path: str, url: str, token: str, *, do_sync: bool = False
    ) -> Any: ...

    def do_sync_on(self, conn: Any) -> None: ...

    def is_supported(self) -> bool: ...
```

- [ ] **Step 1.2: Write `__init__.py` — 集中探针 + 后端工厂**

```python
from ._protocol import TursoBackend

# ── 集中探针：唯一的 HAS_LIBSQL / HAS_PYTURSO 来源 ──
try:
    import turso.sync  # noqa: F401
    HAS_PYTURSO = True
except ImportError:
    HAS_PYTURSO = False

try:
    import libsql  # noqa: F401
    HAS_LIBSQL = True
except ImportError:
    HAS_LIBSQL = False


def get_active_backend() -> TursoBackend:
    if HAS_PYTURSO:
        from ._pyturso import PytursoBackend
        return PytursoBackend()
    if HAS_LIBSQL:
        from ._libsql import LibsqlBackend
        return LibsqlBackend()
    raise RuntimeError("Neither pyturso nor libsql is available")
```

- [ ] **Step 1.3: Syntax check**

```bash
python -m py_compile database/backends/_protocol.py
python -m py_compile database/backends/__init__.py
```

- [ ] **Step 1.4: Commit**

---

## Task 2: Implement `LibsqlBackend` (`_libsql.py`)

**Files:**
- Create: `database/backends/_libsql.py`
- Move from `connection.py`: `_connect_embedded_replica()` (lines 326–476), `_start_pull_monitor()` (lines 302–323), `_query_turso_db_size()` (lines ~270–300)

- [ ] **Step 2.1: Implement `LibsqlBackend` class**

Wrap `_connect_embedded_replica` logic in `connect()`:
- Sidecar cleanup, pull monitoring, `libsql.connect()` with `_check_same_thread=False`
- PRAGMA setup + WAL_CHECKPOINT(TRUNCATE) after initial pull
- Optional `conn.sync()` if `do_sync=True`

`do_sync_on(conn)` — **含鸭子类型安全网**:
```python
def do_sync_on(self, conn: Any) -> None:
    if hasattr(conn, "sync"):  # 保护纯本地 sqlite3.Connection 不崩
        conn.sync()
```

`is_supported()`: return `HAS_LIBSQL`

`name`: `"libsql"`

- [ ] **Step 2.2: Move helper functions**
  - `_start_pull_monitor()` → module-level in `_libsql.py`
  - `_query_turso_db_size()` → module-level in `_libsql.py`

- [ ] **Step 2.3: Syntax check**

```bash
python -m py_compile database/backends/_libsql.py
```

- [ ] **Step 2.4: Commit**

---

## Task 3: Implement `PytursoBackend` (`_pyturso.py`)

**Files:**
- Create: `database/backends/_pyturso.py`
- Move from `connection.py`: `_connect_turso_sync()` (lines 479–550)

- [ ] **Step 3.1: Implement `PytursoBackend` class**

`connect()`:
1. V007 `pre_connect_migrate(db_path)` (keep this call)
2. `turso.sync.connect()`
3. PRAGMA setup
4. If `db_existed_before` and not `do_sync`: pull
5. If `do_sync`: push → pull → checkpoint

`do_sync_on(conn)` — **含鸭子类型安全网**:
```python
def do_sync_on(self, conn: Any) -> None:
    if hasattr(conn, "pull"):  # 保护纯本地 sqlite3.Connection 不崩
        conn.push()
        conn.pull()
        conn.checkpoint()
```

`is_supported()`: return `HAS_PYTURSO`

`name`: `"pyturso"`

- [ ] **Step 3.2: Syntax check**

```bash
python -m py_compile database/backends/_pyturso.py
```

- [ ] **Step 3.3: Commit**

---

## Task 4: Refactor `connection.py` to use backend

**Files:**
- Modify: `database/connection.py`

- [ ] **Step 4.1: 替换探针 + 添加 backend 导入**

删除 `connection.py:36–47` 的 `import libsql`/`import turso.sync` 探针块，改为：
```python
from database.backends import get_active_backend, HAS_LIBSQL, HAS_PYTURSO

_backend = None  # Lazy init

def _get_backend():
    global _backend
    if _backend is None:
        _backend = get_active_backend()
    return _backend
```

`HAS_LIBSQL`/`HAS_PYTURSO` 继续在本模块可用，所有 20+ 处引用无需改动。

- [ ] **Step 4.2: Replace `HAS_PYTURSO`/`HAS_LIBSQL` connect dispatch**

In `_get_main_write_conn_singleton()` (line 779–782):
```python
# Before:
if HAS_PYTURSO:
    conn = _connect_turso_sync(...)
else:
    conn = _connect_embedded_replica(...)
# After:
conn = _get_backend().connect(db_path, url, token, do_sync=do_sync)
```

Same for `_get_hub_write_conn_singleton()` (lines 852–855), `_get_conn()` (lines 978–981), and `_get_cloud_conn()` (lines 1014–1016).

- [ ] **Step 4.3: Replace `hasattr` sync dispatch in health checks**

In `_get_main_write_conn_singleton()` (lines 744–749):
```python
# Before:
if hasattr(conn, "sync"): conn.sync()
elif hasattr(conn, "pull"): conn.push(); conn.pull(); conn.checkpoint()
# After:
_get_backend().do_sync_on(conn)
```

Same for `_get_hub_write_conn_singleton()` (lines 823–828).

- [ ] **Step 4.4: Remove moved functions**

Delete: `_connect_embedded_replica()`, `_connect_turso_sync()`, `_start_pull_monitor()`, `_query_turso_db_size()`.

Delete: `import libsql` / `import turso.sync` 探针块（lines 36–47）— 已集中到 `backends/__init__.py`。

Keep: `HAS_LIBSQL` / `HAS_PYTURSO` — 从 `database.backends` 导入（Step 4.1 已加）。20+ 处引用无需改动。

- [ ] **Step 4.5: Update `_should_use_local_only_connection()`**

Keep the simple `HAS_LIBSQL or HAS_PYTURSO` check — those module-level vars remain (re-exported from backend modules) and are sufficient for a pre-connect availability check.

- [ ] **Step 4.6: Run syntax check + existing tests**

```bash
python -m py_compile database/connection.py
pytest tests/ -v --tb=short -m "not slow"
```

- [ ] **Step 4.7: Commit**

---

## Task 5: Refactor `sync_service.py` to use backend

**Files:**
- Modify: `database/sync_service.py`

- [ ] **Step 5.1: Replace `hasattr` sync dispatch in `_run_libsql_sync_pipeline()`**

Lines 84, 105–119:
```python
# Before:
if hasattr(conn, "pull"):
    conn.push(); conn.pull(); conn.checkpoint()
else:
    conn.sync()

# After:
from database.backends import get_active_backend
get_active_backend().do_sync_on(conn)
```

- [ ] **Step 5.2: Simplify creds_ok check**

In `sync_databases()` (line 165) and `sync_hub_databases()` (line 203):
```python
# Before:
creds_ok = bool(url and token and (connection.HAS_LIBSQL or connection.HAS_PYTURSO))
# After:
creds_ok = bool(url and token and (connection.HAS_LIBSQL or connection.HAS_PYTURSO))
# (Keep as-is — this is a pre-connect check, backend not needed yet)
```

- [ ] **Step 5.3: Run tests**

```bash
python -m py_compile database/sync_service.py
pytest tests/ -v --tb=short -m "not slow"
```

- [ ] **Step 5.4: Commit**

---

## Task 6: Refactor `execution_engine.py` to use backend

**Files:**
- Modify: `database/execution_engine.py`

- [ ] **Step 6.1: Add backend import**

```python
from database.backends import get_active_backend
```

Or use lazy import inside `_sync_daemon` to avoid circular imports.

- [ ] **Step 6.2: Replace sync dispatch in `_sync_daemon` (lines 304–328)**

The sync daemon has 3 `hasattr` check sites. 安全网已内聚到 backend 的 `do_sync_on()` 里，所以调用方可以无脑调用：

1. **Line 304**: `if not (hasattr(conn, "sync") or hasattr(conn, "pull")): continue`
   → 删除该判断。如果 conn 是纯本地 sqlite3，`do_sync_on()` 内部的 hasattr 会静默跳过。

2. **Lines 316–321 + 323–328** (两个分支，锁内/锁外):
   ```python
   if hasattr(conn, "pull"):
       conn.push(); conn.pull(); conn.checkpoint()
   else:
       conn.sync()
   ```
   → 统一替换为: `get_active_backend().do_sync_on(conn)`

最终 `_sync_daemon` 的 sync 代码段简化为：
```python
conn = _get_main_write_conn_singleton(do_sync=False)
conn_lock = _get_singleton_conn_op_lock(conn)
# ...
with conn_lock:
    get_active_backend().do_sync_on(conn)
```

- [ ] **Step 6.3: Run tests**

```bash
python -m py_compile database/execution_engine.py
pytest tests/ -v --tb=short -m "not slow"
```

- [ ] **Step 6.4: Commit**

---

## Task 7: Update `legacy.py` exports

**Files:**
- Modify: `database/legacy.py`

- [ ] **Step 7.1: Add backend re-exports**

```python
from .backends import get_active_backend, TursoBackend
```

Keep existing `HAS_LIBSQL` import from connection.

- [ ] **Step 7.2: Run tests**

```bash
python -m py_compile database/legacy.py
pytest tests/ -v --tb=short -m "not slow"
```

- [ ] **Step 7.3: Commit**

---

## Task 8: Write unit tests for backend Protocol

**Files:**
- Create: `tests/unit/database/backends/test_protocol.py`

- [ ] **Step 8.1: Write tests**

Test cases:
- `get_active_backend()` returns a `TursoBackend` (Protocol check)
- `PytursoBackend.is_supported()` reflects `HAS_PYTURSO`
- `LibsqlBackend.is_supported()` reflects `HAS_LIBSQL`
- `do_sync_on()` dispatches correctly (mock conn with `.sync()` vs `.push()/.pull()/.checkpoint()`)
- **`do_sync_on()` 安全网**: 传入纯 `sqlite3.Connection`（无 `.sync`/`.pull`），不应抛异常
- Backend preference: pyturso > libsql
- **循环导入验证**: `import database.backends` 不触发 circular import

- [ ] **Step 8.2: Run tests**

```bash
pytest tests/unit/database/backends/ -v --tb=short
```

- [ ] **Step 8.3: Commit**

---

## Task 9: Full test suite + cleanup

- [ ] **Step 9.1: Run full regression**

```bash
pytest tests/ -v --tb=short -m "not slow"
```

- [ ] **Step 9.2: Run py_compile on all modified files**

```bash
python -m py_compile database/connection.py
python -m py_compile database/execution_engine.py
python -m py_compile database/sync_service.py
python -m py_compile database/session.py
python -m py_compile database/legacy.py
```

- [ ] **Step 9.3: Verify line count reduction**

```bash
wc -l database/connection.py  # Target: ~400 lines (was 1255)
```

- [ ] **Step 9.4: Final commit**

---

## Spec Coverage Checklist

| Design Element | Covered In |
|---|---|
| Protocol definition | Task 1 |
| LibsqlBackend | Task 2 |
| PytursoBackend | Task 3 |
| connection.py refactoring | Task 4 |
| sync_service.py refactoring | Task 5 |
| execution_engine.py refactoring | Task 6 |
| legacy.py updates | Task 7 |
| Unit tests | Task 8 |
| Full regression | Task 9 |

## Deferred Items

1. **`database/README.md` doc update**: Update WalConflict notes to reference backend Protocol instead of raw `hasattr` checks. Low priority, can be follow-up.
2. **`_query_turso_db_size()`**: Currently only used by `_connect_embedded_replica()`. If pyturso backend wants it later, can add separately.
