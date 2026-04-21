# database Package Architecture

This package splits the old `db_manager.py` into clear layers while preserving runtime behavior and improving safety in Embedded Replica mode.

> `core/db_manager.py` remains as a 3972-line compatibility facade for legacy callers, but all new code should depend on the submodules below directly.

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

## Runtime Iron Rules（运行期铁律）

> 本节是 WalConflict / 连接中毒等事故后沉淀的**具体操作守则**。
> 与 [`docs/dev/AI_CONTEXT.md`](../docs/dev/AI_CONTEXT.md) §3.1 的 MUST 规则配合：那里讲"必须做什么"，这里讲"具体怎么做"。
>
> 核心准则：**进程绝对唯一，连接绝对单例，游标绝对关闭，读后绝对释放。**

### 1. 进程级防御（OS Process Lock）

- **绝对禁止多开套娃**：不得使用 `subprocess.run` 重新拉起带不同环境变量的主程序。环境变量热重载必须在内存中用 `importlib.reload()` 解决（参考 `main.py` 的早启动钩子）。
- **强制物理锁**：入口文件在连接任何数据库之前，必须通过 `msvcrt` (Windows) 或 `fcntl` (Unix) 抢占 `data/.process.lock`。抢锁失败必须立即 `sys.exit(1)`。

### 2. 连接级防御（Singleton Connection）

- **全局单例**：对同一个本地副本 `.db` 文件，全局只能保持**唯一一个**持久化 `libsql` 连接对象。
- **禁止私自建连**：业务代码绝对禁止直接调用 `libsql.connect(DB_PATH)`。所有读写必须走 `connection.py` 提供的单例接口（如 `_get_read_conn`）。

### 3. 游标与读锁协议 🌟（最易犯错点）

SQLite 的 `SELECT` 会隐式开启共享读事务。不显式清理将永久锁死 WAL 文件、导致 `conn.sync()` 崩溃。

任何查询操作必须严格遵循以下 `try...finally` 模板：

- **必选 1**：包裹在单例线程锁（`with conn_lock:`）内。
- **必选 2**：`finally` 块中 `cur.close()`——清除 `SQLITE_ROW` 状态。
- **必选 3**：查询结束后 `c.commit()`——释放底层读锁。
- **禁忌**：绝对禁止匿名游标（如 `conn.execute("SELECT ...")`）。

正确模板：

```python
c = connection._get_read_conn(DB_PATH)
conn_lock = connection._get_singleton_conn_op_lock(c)
if conn_lock is not None:
    with conn_lock:
        cur = c.cursor()
        try:
            cur.execute("SELECT ...")
            res = cur.fetchone()  # 或 fetchall()
        finally:
            cur.close()  # 第一道防线：重置语句状态
        c.commit()        # 第二道防线：释放底层读锁
```

### 4. 写事务与自愈机制

- **显式排他锁**：批量写入必须 `cur.execute("BEGIN IMMEDIATE")`，避免死锁。
- **回滚兜底**：写操作 `try...except` 中发生任何异常必须 `conn.rollback()`。
- **静默自愈（Poisoned Connection Recovery）**：底层抛出 `invalid state, started with Txn` / `WalConflict` / `stream not found` / `hrana 断连` 异常时，说明单例已损坏或被云端踢出。守护线程必须捕获这些关键字，强制 `_close_main_write_conn_singleton()` 销毁旧连接，下一次循环静默重建重试。

### 5. GC Hack（conn.sync() 前强制回收）

调用底层 `conn.sync()` 同步增量帧到云端**之前**，必须强制 `import gc; gc.collect()`。此举物理销毁业务层可能因漏写 `cur.close()` 而游荡在内存中的僵尸游标对象，确保 WAL 文件处于绝对干净的解锁状态。

### 6. 本地 WAL 并发配置（生产值）

所有本地 libsql / sqlite3 连接初始化时必须设置：

| PRAGMA | 值 | 作用 |
| --- | --- | --- |
| `journal_mode` | `WAL` | 写前日志模式，允许读写并发 |
| `synchronous` | `NORMAL` | 性能/安全折衷 |
| `busy_timeout` | `5000` | WAL 锁冲突时自动重试 5 秒（而非立即失败） |
| `wal_autocheckpoint` | `1000` | 每 1000 页自动 checkpoint，避免 WAL 文件无限增长 |
| 连接 `timeout` | `20.0` | 写入竞争兜底超时 |

落地点：`_open_local_connection`、`_connect_embedded_replica`、`_get_hub_local_conn._open_local_connection`（均在 `connection.py`）。

### 7. 批量写入重试守则

`_execute_batch_writes()` 对 WAL 冲突采用 **3 次指数退避**：100ms → 200ms → 400ms。
其它异常不重试，直接抛出。

`_writer_daemon` 遇 WAL 冲突时**保留 batch**、睡 500ms 等 replica 同步窗口；其它异常则**清空 batch** 避免重复处理。这两种策略配合保证批量写入最终落库且不阻塞守护线程。

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
