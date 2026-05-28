# database Package Architecture

This package splits the old `db_manager.py` into clear layers while preserving runtime behavior and documenting the current pyturso runtime.

> `core/db_manager.py` has been removed (2026-04-22). New code should depend on the specific submodules directly.

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
- pyturso connect/retry logic and read/write path dispatch
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

### 2. 连接级防御（Read/Write Path Dispatch）

- **写单例只用于同步窄路径**：`_get_main_write_conn_singleton()` 和 `_get_hub_write_conn_singleton()` 只在 `do_sync=True` 的窄路径下复用；普通业务写入仍应通过连接工厂按需获取连接。
- **读连接按需独立获取**：查询路径使用 `_get_read_conn()` / `_get_local_read_conn()`，不要把读路径绑定到写单例。
- **禁止私自建连**：业务代码不得绕过 `database/connection/` 直接打开 Turso/SQLite 连接。

### 3. 游标协议 🌟（最易犯错点）

查询操作必须明确关闭游标，避免长时间持有连接状态：

- **必选 1**：使用显式游标对象，不要把复杂查询塞进匿名 `conn.execute(...)` 链式调用里。
- **必选 2**：`finally` 块中 `cur.close()`，确保语句状态及时释放。
- **必选 3**：如果查询后还会继续持有连接，请尽早返回或进入下一段明确的短事务。

正确模板：

```python
c = connection._get_read_conn(DB_PATH)
cur = c.cursor()
try:
  cur.execute("SELECT ...")
  res = cur.fetchone()  # 或 fetchall()
finally:
  cur.close()
```

### 4. 写事务与自愈机制

- **显式排他锁**：批量写入必须 `cur.execute("BEGIN IMMEDIATE")`，避免死锁。
- **回滚兜底**：写操作 `try...except` 中发生任何异常必须 `conn.rollback()`。
- **静默自愈（Poisoned Connection Recovery）**：底层抛出 `invalid state, started with Txn` / `WalConflict` / `stream not found` / `hrana 断连` 异常时，说明单例已损坏或被云端踢出。守护线程必须捕获这些关键字，强制 `_close_main_write_conn_singleton()` 销毁旧连接，下一次循环静默重建重试。

### 5. 同步清理

当前 pyturso 后端不依赖手动 `gc.collect()` 作为同步前置条件。同步清理由 `backend.do_sync_on(conn)` 和连接关闭流程负责；真正要防的是漏关游标和越层直连。

### 6. 本地 WAL 并发配置（生产值）

所有本地 pyturso / sqlite3 连接初始化时必须设置：

| PRAGMA | 值 | 作用 |
| --- | --- | --- |
| `journal_mode` | `WAL` | 写前日志模式，允许读写并发 |
| `synchronous` | `NORMAL` | 性能/安全折衷 |
| `busy_timeout` | `5000` | WAL 锁冲突时自动重试 5 秒（而非立即失败） |
| `wal_autocheckpoint` | `1000` | 每 1000 页自动 checkpoint，避免 WAL 文件无限增长 |
| 连接 `timeout` | `20.0` | 写入竞争兜底超时 |

落地点：`_open_local_connection`、`_get_local_read_conn`、`_get_hub_local_conn._open_local_connection`（均在 `connection.py`）。

### 7. 批量写入重试守则

`_execute_batch_writes()` 对 WAL 冲突采用 **3 次指数退避**：100ms → 200ms → 400ms。
其它异常不重试，直接抛出。

`_writer_daemon` 遇 WAL 冲突时**保留 batch**、睡 500ms 等 replica 同步窗口；其它异常则**清空 batch** 避免重复处理。这两种策略配合保证批量写入最终落库且不阻塞守护线程。

## Critical Safety Rule: Read/Write Path Separation

This rule is mandatory.

- Main DB reads use `_get_read_conn()` / `_get_local_read_conn()` and are independent from the write singleton.
- Main DB sync / flush paths may use `_get_main_write_conn_singleton(do_sync=True)`.
- Hub reads use `_get_hub_local_conn()` / `_get_hub_write_conn_singleton()` according to the same read/write split.
- No code path should bypass `database/connection/` and open raw connection handles directly.

## WalConflict Root Cause Summary

`WalConflict` historically came from mixing long-lived connection reuse with background sync on the same file. The current fix is architectural: keep sync on the write/sync path, keep reads on separate short-lived read connections, and close cursors promptly.

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

- No helper opens raw connection handles outside `database/connection/`.
- `_get_read_conn_impl` still dispatches to the read path for normal reads and to the write singleton only for `do_sync=True`.
- Hub reads still respect the same read/write split.
- New business modules only depend on `connection/utils/schema` and do not redefine connection logic.
