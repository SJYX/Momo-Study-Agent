# [Rule] Turso libsql (Embedded Replica) 并发与防冲突 (WalConflict) 开发守则

## 0. 背景与核心哲学
在处理 Turso 的嵌入式本地副本（Embedded Replica）时，底层的 Rust 同步引擎对 SQLite 的 `.db-wal` 文件锁极其敏感。任何跨进程的多开、悬空游标（Dangling Cursors）、未释放的读锁（Shared Locks）都会导致 `libsql::sync : WalConflict` 甚至连接中毒（`invalid state, started with Txn`）。
**核心准则：进程绝对唯一，连接绝对单例，游标绝对关闭，读后绝对释放。**

## 1. 进程级防御 (OS Process Lock)
- **绝对禁止多开套娃**：禁止在代码中使用 `subprocess.run` 重新拉起带不同环境变量的主程序。环境变量热重载必须在内存中使用 `importlib.reload()` 解决。
- **强制物理锁**：入口文件（如 `main.py`）必须在连接任何数据库前，通过 `msvcrt` (Windows) 或 `fcntl` (Unix) 抢占物理 `.process.lock` 文件。抢锁失败必须立即 `sys.exit(1)`。

## 2. 连接级防御 (Singleton Connection)
- **全局单例**：对同一个本地副本 `.db` 文件，全局只能保持**唯一一个**持久化的 `libsql` 连接对象。
- **禁止私自建连**：业务代码绝对禁止直接调用 `libsql.connect(DB_PATH)`。所有读写操作必须通过 `connection.py` 提供的单例获取接口（如 `_get_read_conn`）。

## 3. 游标与读锁协议 (The Cursor & Read-Lock Protocol) - 🌟 最易犯错点！
SQLite 的 `SELECT` 语句会隐式开启共享读事务。如果不显式清理，将永久锁死 WAL 文件导致 `conn.sync()` 崩溃。
任何查询操作必须严格遵循以下 `try...finally` 闭环模板：
- **必选项 1**：必须包裹在单例线程锁（如 `with conn_lock:`）内。
- **必选项 2**：必须在 `finally` 块中调用 `cur.close()`。彻底清除 `SQLITE_ROW` 状态。
- **必选项 3**：必须在查询结束后调用 `c.commit()`。彻底释放 SQLite 底层读锁。
- **禁忌**：绝对禁止使用匿名游标（如 `conn.execute("SELECT...")`）。

**✅ 正确的查询模板：**
```python
c = connection._get_read_conn(DB_PATH)
conn_lock = connection._get_singleton_conn_op_lock(c)
if conn_lock is not None:
  with conn_lock:
    cur = c.cursor()
    try:
      cur.execute("SELECT ...")
      res = cur.fetchone() # 或 fetchall()
    finally:
      cur.close()  # <--- 第一道防线：重置语句状态
    c.commit()       # <--- 第二道防线：释放底层读锁
```

## 4. 写事务与自愈机制 (Write & Self-Healing)
- 显式排他锁：批量写入必须使用显式的 cur.execute("BEGIN IMMEDIATE")，防止死锁。
- 回滚兜底：写操作的 try...except 块中，发生任何异常必须执行 conn.rollback()。
- 静默自愈 (Poisoned Connection Recovery)：如果底层抛出 invalid state, started with Txn, WalConflict, stream not found, 或 hrana 断连异常，说明单例连接已损坏/被云端踢出。必须在守护线程中捕获这些关键字，强制执行 _close_main_write_conn_singleton() 销毁旧连接，并在下一次循环中静默重建重试。

## 5. 垃圾回收核弹 (The GC Hack)
在调用底层的 conn.sync() 同步增量帧到云端之前，必须强制调用一次 import gc; gc.collect()。此举旨在物理销毁业务层（如各类 Manager 脚本中）可能因漏写 cur.close() 而游荡在内存中的僵尸游标对象，确保 WAL 文件处于绝对干净的解锁状态。

# database Package Architecture

This package splits the old `db_manager.py` into clear layers while preserving runtime behavior and improving safety in Embedded Replica mode.

## Why This Refactor

The previous single-file design mixed:

- connection infrastructure
- migration/schema code
- hub user business logic
- word/note business logic
- utility helpers

This made it easy to accidentally re-introduce unsafe connection patterns and hard to reason about WAL behavior.

## Module Boundaries

### 1) `database/connection.py`

Responsibilities:

- Connection lifecycle and context resolution
- Embedded Replica connect/retry logic
- Main DB and Hub DB singleton write connections
- Writer queue and background writer thread
- Background sync daemon
- Managed connection execution helpers
- Hub read helpers (`_hub_fetch_one_dict`, `_hub_fetch_all_dicts`)

Non-responsibilities:

- No business rules about users/words
- No schema DDL ownership (only callback registration/dispatch)

### 2) `database/utils.py`

Responsibilities:

- Secret encryption/decryption
- Text cleaning helpers (`clean_for_maimemo`)
- Error classification helpers
- Hash/fingerprint helpers
- Prompt hash/archive helpers
- Cloud target discovery/caching helpers
- Generic throttled logging helper utilities

### 3) `database/schema.py`

Responsibilities:

- Main schema creation and migration (`_create_tables`)
- Hub schema creation (`_init_hub_schema`)
- Initialization entrypoints (`init_db`, `init_users_hub_tables`)
- Table-existence and init-marker caching logic
- Hub init state persistence/cache

Notes:

- `schema.py` registers schema initializer callbacks into `connection.py`.
- This keeps dependency direction one-way (schema -> connection), avoiding circular imports.

### 4) `database/hub_users.py`

Responsibilities:

- Hub user profile CRUD-like operations
- Hub credential save/read (encrypted fields)
- Session/statistics updates
- Admin action logging and listing
- Hub user status operations

Dependencies:

- Reads/writes via `connection.py`
- Crypto/time helpers via `utils.py`

### 5) `database/momo_words.py`

Responsibilities:

- Main DB word/note business operations
- Processed status operations
- Progress snapshot operations
- Unsynced note retrieval/recovery paths
- Community batch lookup helpers
- Config read/write wrappers
- Sync wrapper functions (`sync_databases`, `sync_hub_databases`)

Dependencies:

- DB access via `connection.py`
- Utility helpers via `utils.py`
- Schema callbacks/helpers where needed

## Critical Safety Rule: Embedded Replica Single Connection Rule

This rule is mandatory.

In Embedded Replica mode, for the same replica file:

- Do NOT open extra libsql connections for read paths.
- Do NOT keep thread-local read connections.
- Do NOT create any additional `libsql.connect(local_replica_path)` handles alongside the active syncing singleton.

### Required Behavior

- Main DB reads and writes must reuse the process singleton:
  - `_get_main_write_conn_singleton(...)`
- Hub DB reads and writes must reuse the process singleton:
  - `_get_hub_write_conn_singleton(...)`
- `_get_read_conn_impl(...)` must return main singleton in Embedded Replica mode.
- Hub fetch helpers must read through hub singleton.

### Forbidden Patterns

- ThreadLocal read connection caches for libsql replicas
- `_get_libsql_local_read_conn(...)` style APIs for primary replica files
- Any code path that opens a second live connection to the same syncing replica file

## WalConflict Root Cause Summary

`WalConflict` appears when multiple libsql connection instances compete on the same replica file while one is actively syncing WAL frames. The Rust core enforces strict file-level synchronization assumptions that are violated by multi-instance access.

The fix is architectural, not just retry-based:

- one replica file
- one live libsql connection singleton
- all operations serialized via connection-level locks and/or queueing

## Dependency Direction (No Circular Imports)

Recommended import direction:

- `utils` -> independent
- `connection` -> may import from `utils`
- `schema` -> imports `connection` + `utils`
- `hub_users` -> imports `connection` + `utils` (+ `schema` entrypoint where needed)
- `momo_words` -> imports `connection` + `utils` (+ `schema` helpers where needed)

Avoid reverse imports (e.g. `connection` importing `hub_users` or `momo_words`).

## Operational Notes

- Writer queue serializes write operations to reduce lock contention.
- Sync daemon performs debounce-style background sync for main DB singleton.
- Local corruption recovery keeps WAL sidecar files untouched to avoid unsafe deletion behavior.

## Migration Checklist for Future Changes

Before merging DB-related changes, verify:

- No new ThreadLocal read connection logic exists for Embedded Replicas.
- No helper opens extra libsql local connections to active replica files.
- `_get_read_conn_impl` still funnels to main singleton in cloud mode.
- Hub reads still use hub singleton.
- New business modules only depend on `connection/utils/schema` and do not redefine connection logic.
