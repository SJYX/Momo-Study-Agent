# Findings — Embedded Replica Code Cleanup (Protocol Abstraction)

## Task Goal

Clean up the dual-backend (libsql / pyturso) coexistence code by introducing a `TursoBackend` Protocol, splitting backend-specific logic into `database/backends/`, and making pyturso the preferred default path. Both backends are retained (libsql stays as Windows fallback).

## Current Architecture (2026-05-20)

### Three eras of DB architecture
1. **Old**: Manual dual-write with `libsql-client` (deprecated)
2. **Embedded Replica** (Phases 0–4): `libsql` SDK — `libsql.connect(path, sync_url=url, auth_token=token)` — single connection, `conn.sync()`
3. **Pyturso** (current preferred): `pyturso` — `turso.sync.connect(path, ...)` — `push() → pull() → checkpoint()`

### Key files and line counts
| File | Lines | Role |
|------|-------|------|
| `database/connection.py` | 1255 | Singleton mgmt, both connect functions, read resolution, health checks |
| `database/execution_engine.py` | 503 | Write queue, sync daemon, `hasattr(conn, "pull")` dispatch |
| `database/sync_service.py` | 245 | Sync pipeline, `hasattr(conn, "pull")` dispatch |
| `database/session.py` | 280 | DBSession wrapper |
| `database/legacy.py` | ~60 | Drop-in facade, re-exports |
| `database/migrations/V007_migrate_db_format.py` | 225 | libsql → pyturso format migration (MUST KEEP) |

### Backend-specific code locations
- **`_connect_embedded_replica()`**: connection.py:326–476 (151 lines) — libsql connect + pull monitor + WAL checkpoint stabilization
- **`_connect_turso_sync()`**: connection.py:479–550 (72 lines) — pyturso connect + V007 pre-migration
- **`_start_pull_monitor()`**: connection.py:302–323 — libsql-specific pull progress monitor
- **Sync dispatch (`hasattr`)**:
  - connection.py:744–749 (`_get_main_write_conn_singleton` health check)
  - connection.py:823–828 (`_get_hub_write_conn_singleton` health check)
  - connection.py:978–981 (`_get_conn` connect dispatch)
  - sync_service.py:84, 105–119 (`_run_libsql_sync_pipeline`)
  - execution_engine.py:~177 (sync daemon)

### User constraints
- **libsql CANNOT be removed**: pyturso Windows compilation is complex; libsql must remain as fallback
- **V007 migration MUST be kept**: only "asher" migrated; other users still on old format; V007 auto-migrates on first connect
- **pyturso is preferred default** when available
- **`HAS_LIBSQL` detection must stay** for Windows fallback

### Runtime detection (connection.py:36–47)
```python
try:
    import libsql
    HAS_LIBSQL = True
except ImportError:
    HAS_LIBSQL = False

try:
    import turso.sync
    HAS_PYTURSO = True
except ImportError:
    HAS_PYTURSO = False
```

### Current sync API differences
| Operation | libsql | pyturso |
|-----------|--------|---------|
| Sync | `conn.sync()` | `conn.push()` → `conn.pull()` → `conn.checkpoint()` |
| Detection | `hasattr(conn, "sync")` | `hasattr(conn, "pull")` |
| Health check | `conn.execute("SELECT 1")` | `conn.execute("SELECT 1")` (same) |
| PRAGMA | `busy_timeout=30000; synchronous=NORMAL` | same |
| Close | `conn.close()` | `conn.close()` (same) |

## Key Decisions Made

1. **Protocol abstraction (方案 B)** — user chose this over minimal extraction (A) or middle-ground (C)
2. **4 methods in Protocol**: `connect()`, `do_sync_on()`, `is_supported()`, `name`
3. **Separate files**: `_libsql.py`, `_pyturso.py` in `database/backends/`
4. **V007 migration stays in pyturso backend** (called inside `connect()`)
5. **`_start_pull_monitor()` goes to `_libsql.py`** (only libsql has pull monitoring)
6. **鸭子类型安全网内聚到 Backend** — `do_sync_on()` 内部做 `hasattr` 检查，保护纯本地 sqlite3.Connection
7. **`HAS_LIBSQL`/`HAS_PYTURSO` 集中在 `backends/__init__.py`** — 顶部探测导出，无懒加载心智负担

## Review Findings (2026-05-20)

### Issues found and fixed in plan
1. **遗漏 `_get_cloud_conn()`**: connection.py:1014–1016 有第 4 个 `HAS_PYTURSO` connect dispatch，Plan 已补充
2. **execution_engine.py 细节不足**: `_sync_daemon` 有 3 个 `hasattr` 位置（304, 316, 323），Plan Task 6 已补充完整替换指引
3. **循环导入风险**: `_libsql.py` → `execution_engine` → `connection` → `backends/__init__` → `_libsql.py`。**已修复**：所有跨层导入改为函数内懒导入
4. **致命：纯本地 SQLite 调用 `do_sync_on` 崩溃** — 旧代码的 `hasattr` 不仅区分后端，还保护纯本地 `sqlite3.Connection`。**已修复**：安全网内聚到 backend 的 `do_sync_on()` 实现里（`hasattr(conn, "sync")` / `hasattr(conn, "pull")`），调用方无脑调 `do_sync_on()` 即可
5. **`HAS_LIBSQL`/`HAS_PYTURSO` 归属混乱** — 不应通过懒加载计算。**已修复**：`backends/__init__.py` 顶部集中探测并导出，所有外部模块直接 `from database.backends import HAS_LIBSQL, HAS_PYTURSO`

### 已确认未遗漏的 `hasattr` 分发点
- connection.py:459 → 在 `_connect_embedded_replica()` 内部，随函数移到 `_libsql.py`，无需替换
- sync_service.py:84, 105, 113 → Task 5 覆盖
- execution_engine.py:304, 316, 323 → Task 6 覆盖

### `HAS_LIBSQL`/`HAS_PYTURSO` 使用点（必须保留）
共 20+ 处引用，分布在 5 个模块。这些是预连接可用性检查，不需要 backend 实例。
移除 `import libsql`/`import turso.sync` 后，需从 backend 模块懒导入计算。

## Errors Encountered
_(none yet — implementation not started)_
