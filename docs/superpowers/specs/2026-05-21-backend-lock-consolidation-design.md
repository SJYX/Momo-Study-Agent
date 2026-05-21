# Backend 锁下沉 + 环境探针清理 + Web 即时同步 设计文档

> 日期: 2026-05-21
> 背景: pyturso 引擎已支持 MVCC 并发读写，但外部 conn_op_lock 仍串行化所有路径；环境探针存在冗余；Web UI 保存后无即时云端同步。

---

## 评估结论

### ✅ 点 2（纯本地 SQLite 多态保护）— 已完成，无需改动

`LibsqlBackend.do_sync_on()` (line 287) 和 `PytursoBackend.do_sync_on()` (line 217) 均已有 `hasattr` 鸭类型保护。纯本地 `sqlite3.Connection` 传入时直接 no-op。单测 `test_protocol.py:60-69` 覆盖此路径。**不改。**

### ✅ 点 3（环境探针集中管理）— 部分完成，需清理冗余

集中源 `database/backends/__init__.py:3-14` 已存在，`connection.py` / `sync_service.py` 等已从集中源导入。

**待清理：**
- `_pyturso.py:14-19` 自行做 `try: import turso.sync` 冗余探针
- `_libsql.py:17-22` 自行做 `try: import libsql` 冗余探针

V007 迁移文件（`V007_migrate_db_format.py`）内**无** `HAS_PYTURSO` 引用，由 `_pyturso.py` 懒加载调用，**无冗余代码需清理**。

### 🔧 点 1（管理锁全面下沉）— 核心改动，范围大

### 🔧 点 4（Web 即时同步 + 去抖）— 新增功能

---

## 设计：点 1 — 锁全面下沉到 Backend 内部

### 1.1 问题现状

当前 `_main_write_conn_op_lock` / `_hub_write_conn_op_lock` 在 `connection.py:126/131` 定义，由 **27+ 调用点** 在外部显式获取后包裹数据库操作。两个 backend 内部完全无锁。

对于 pyturso 路径，外部锁是多余的 — pyturso 引擎原生 MVCC，`conn.push()` / `conn.pull()` / `conn.checkpoint()` 可安全并发调用。

对于 libsql 路径，锁是必要的（防止 `SQLITE_BUSY` / WAL 冲突），但当前由外部管理，backend 自身没有自包含的并发保护。

### 1.2 目标架构

```
┌─────────────────────────────────────────────────────────────┐
│ 外部调用点（connection.py, execution_engine.py,              │
│ session.py, sync_service.py, notes_repo.py, stats.py, etc.）│
│                                                               │
│   before: conn_lock = _get_singleton_conn_op_lock(conn)      │
│           if conn_lock: with conn_lock: do_stuff(conn)       │
│           else: do_stuff(conn)                               │
│                                                               │
│   after:  with get_active_backend().op_lock_for(conn):       │
│               do_stuff(conn)                                 │
│                                                               │
│   （PytursoBackend.op_lock_for() → _NoOpContextManager）      │
│   （LibsqlBackend.op_lock_for() → main_lock / hub_lock）      │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 实现方案

#### Protocol 扩展

```python
# database/backends/_protocol.py
from contextlib import contextmanager
from typing import Any, Iterator

@runtime_checkable
class TursoBackend(Protocol):
    name: str
    @contextmanager
    def op_lock_for(self, conn: Any) -> Iterator[None]: ...
    def connect(...) -> Any: ...
    def do_sync_on(conn) -> None: ...
    def is_supported() -> bool: ...
```

#### LibsqlBackend 实现（两把锁 + 动态分发）

```python
# database/backends/_libsql.py
import threading
from contextlib import contextmanager
from typing import Any, Iterator

class LibsqlBackend:
    def __init__(self):
        self._main_lock = threading.Lock()
        self._hub_lock = threading.Lock()

    @contextmanager
    def op_lock_for(self, conn: Any) -> Iterator[None]:
        """根据连接类型分发到 main 或 hub 锁。"""
        lock = self._resolve_lock(conn)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    def _resolve_lock(self, conn: Any) -> threading.Lock:
        """判断 conn 属于 main 还是 hub，返回对应锁。"""
        # 连接在 connect() 时会被标记 _momo_db_role = "main" | "hub"
        role = getattr(conn, "_momo_db_role", None)
        if role == "hub":
            return self._hub_lock
        return self._main_lock
```

**锁绑定时机**：在 `LibsqlBackend.connect()` 中，创建连接后立即标记角色：
```python
conn._momo_db_role = "hub" if "hub" in db_path else "main"
```

#### PytursoBackend 实现（零锁）

```python
# database/backends/_pyturso.py
from contextlib import contextmanager
from typing import Any, Iterator

class PytursoBackend:
    @contextmanager
    def op_lock_for(self, conn: Any) -> Iterator[None]:
        """pyturso 引擎原生 MVCC，无需外部锁。"""
        yield
```

#### 外部调用点统一模板

```python
# Before (所有 27 个调用点的当前模式):
conn_lock = _get_singleton_conn_op_lock(conn)
if conn_lock is not None:
    with conn_lock:
        do_stuff(conn)
else:
    do_stuff(conn)

# After:
with get_active_backend().op_lock_for(conn):
    do_stuff(conn)
```

当 backend 是 PytursoBackend 时，`op_lock_for()` 是 no-op → 零开销，MVCC 全并发。
当 backend 是 LibsqlBackend 时，`op_lock_for(conn)` 自动分发到 main_lock 或 hub_lock → 防 SQLITE_BUSY，main/hub 互不阻塞。

### 1.4 需改动的调用点清单

**Category (a) — 直接引用 `_main_write_conn_op_lock` (7 sites)：**

| 文件 | 行 | 改动 |
|------|----|------|
| `database/connection.py` | 422 | health check: `with _main_write_conn_op_lock:` → `with _get_backend().op_lock_for(conn):` |
| `database/connection.py` | 496 | hub health check: 同上 |
| `database/sync_service.py` | 171 | 移除 `conn_op_lock=` 参数传递 |
| `database/sync_service.py` | 215 | 同上 |
| `database/schema.py` | 284 | `init_db` DDL block: `with connection._main_write_conn_op_lock:` → `with _get_backend().op_lock_for(conn):` |
| `database/schema.py` | 318 | `apply_migrations(lock=...)` 调用改为无锁参数 |
| `database/schema.py` | 403-407, 455-456 | `init_hub_db`: 同上模式 |

**Category (b) — 通过 `_get_singleton_conn_op_lock()` (16 sites)：**

统一改为 `with get_active_backend().op_lock_for(conn):` 模式。

| 文件 | 行 | 函数 |
|------|----|------|
| `database/connection.py` | 745 | `_run_with_managed_connection()` |
| `database/connection.py` | 799 | `_hub_fetch_one_dict()` |
| `database/connection.py` | 849 | `_hub_fetch_all_dicts()` |
| `database/execution_engine.py` | 137 | `_execute_batch_writes()` |
| `database/execution_engine.py` | 305 | `_sync_daemon()` |
| `database/session.py` | 187, 252 | `with_read_session`, `with_write_session` |
| `database/notes_repo.py` | 487 | `atomic_save_iteration_and_update_note()` |
| `database/community_lookup.py` | 169 | `_fetch_notes_from_current_db()` |
| `core/weak_word_filter.py` | 136 | `_get_user_stats()` |
| `core/iteration_manager.py` | 162, 336 | `_get_last_recorded_fam()`, `_record_level_change()` |
| `web/backend/routers/stats.py` | 37, 128, 149 | stats endpoints |
| `web/backend/routers/ops.py` | 118 | ops endpoint |

**Category (c) — 接收 lock 参数的消费者 (4 sites)：**

| 文件 | 改动 |
|------|------|
| `database/session.py` | `DBSession.__init__(lock=None)` → 改为接收 backend 引用或移除 lock 参数 |
| `database/sync_service.py` | `_run_libsql_sync_pipeline(conn_op_lock=...)` → 移除参数 |
| `database/migrations/runner.py` | `apply_migrations(lock=None)` → 移除 lock 参数 |
| `database/community_lookup.py` | `_safe_cursor(lock=None)` → 移除 lock 参数 |

**删除的代码：**
- `database/connection.py:126` `_main_write_conn_op_lock` 变量定义
- `database/connection.py:131` `_hub_write_conn_op_lock` 变量定义
- `database/connection.py:280-285` `_get_singleton_conn_op_lock()` 函数
- `database/connection.py:287` `_is_main_write_singleton_conn()` 函数（如果不再需要）
- `database/connection.py:290` `_is_hub_write_singleton_conn()` 函数（如果不再需要）

**测试更新：**
- `tests/core/test_weak_word_filter.py:83`
- `tests/web/test_words.py:15`
- `tests/web/test_stats.py:20,63,86`
- `tests/web/test_sync.py:15,29,50,88,101`
- `tests/unit/database/test_read_conn_isolation.py:71,205`
- `tests/unit/database/test_sync_service_skip_paths.py:51,77,112,141`

### 1.5 风险与注意事项

1. **`DBSession` 的 read lock 机制**：当前 `DBSession._acquire_read_lock()` (session.py:41-65) 对 singleton 连接做 blocking acquire，对非 singleton 做 timeout acquire。下沉后 pyturso 路径 read lock 变为 no-op（正确），libsql 路径保留同步阻塞（正确）。不保留 timeout 语义 — libsql 下超时后继续读大概率撞 SQLITE_BUSY，直接阻塞最安全。

2. **schema DDL 的 `BEGIN IMMEDIATE`**：`schema.py:284` 的 DDL 块使用 `BEGIN IMMEDIATE` 本身就带写锁，外部 `conn_op_lock` 是双保险。下沉后 `BEGIN IMMEDIATE` 仍然提供数据库级保护，backend 的 `op_lock` 提供进程级保护。

3. **Hub vs Main 锁隔离**：LibsqlBackend 内部使用 `_main_lock` 和 `_hub_lock` 两把独立锁，通过 `op_lock_for(conn)` 根据 `conn._momo_db_role` 动态分发。背单词（main）和社区词典查询（hub）不会互相阻塞。

---

## 设计：点 3 — 清理冗余探针

### 改动

**`database/backends/_pyturso.py`** 行 14-19：
```python
# Before:
try:
    import turso.sync
    HAS_PYTURSO = True
except ImportError:
    HAS_PYTURSO = False

# After:
from database.backends import HAS_PYTURSO
```

**`database/backends/_libsql.py`** 行 17-22：
```python
# Before:
try:
    import libsql
    HAS_LIBSQL = True
except ImportError:
    HAS_LIBSQL = False

# After:
from database.backends import HAS_LIBSQL
```

注意：由于 `__init__.py` 中 `_pyturso` 和 `_libsql` 是懒加载（`get_active_backend()` 内 `from ._pyturso import ...`），此处从父模块导入不会产生循环依赖。

### 影响

- `_pyturso.py` 中 `is_supported()` (line 39) 和 `connect()` (line 58) 中引用的 `HAS_PYTURSO` 行为不变
- `_libsql.py` 中 `is_supported()` (line 132) 和 `connect()` (line 146) 中引用的 `HAS_LIBSQL` 行为不变
- 消除 2 处冗余 try/except ImportError

---

## 设计：点 4 — Web UI 即时同步 + 去抖

### 需求

用户在 Web UI 编辑笔记后，系统应在 ~1-2 秒内完成云端 push+pull，而非等待 sync daemon 的 5 秒空闲 + 2 秒轮询（总计 6-7 秒延迟）。

**约束：** 绝不在路由处理函数中同步调用 `do_sync_on()`（会阻塞 HTTP 响应）。必须异步非阻塞。

### 方案：SyncDebouncer 去抖 + TaskRegistry 线程池执行

#### 新增去抖模块

```python
# database/sync_debouncer.py

import threading
import time
from typing import Optional, Callable

class SyncDebouncer:
    """去抖同步触发器：N 秒空闲后执行一次 sync。"""

    def __init__(self, delay: float = 1.5):
        self._delay = delay
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def trigger(self, fn: Callable[[], None]) -> None:
        """重置去抖计时器。如果已有待执行的 timer，取消并重新创建。"""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay, fn)
            self._timer.daemon = True
            self._timer.start()

    def flush(self, fn: Callable[[], None]) -> None:
        """立即执行（绕过去抖）。"""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        fn()
```

#### Web 路由改动

```python
# web/backend/routers/words.py — PUT /{voc_id}

@router.put("/{voc_id}")
@catch_api_errors("UPDATE_ERROR")
async def update_word_note(
    voc_id: str,
    body: dict,
    ctx = Depends(get_user_context),
):
    memory_aid = body.get("memory_aid", "")
    ok = await run_in_threadpool(update_memory_aid, voc_id, memory_aid, db_path=ctx.db_path)
    if not ok:
        raise HTTPException(status_code=500, detail="UPDATE_FAILED")

    # ⬇️ 新增：后台去抖触发云端同步（SyncDebouncer 去抖 + TaskRegistry 线程池执行）
    from database.sync_debouncer import get_sync_debouncer
    from web.backend.tasks import get_task_registry
    from database.backends import get_active_backend
    from database.connection import _get_main_write_conn_singleton

    def _do_sync():
        conn = _get_main_write_conn_singleton()
        get_active_backend().do_sync_on(conn)

    debouncer = get_sync_debouncer()
    debouncer.trigger(lambda: get_task_registry().submit(_do_sync))

    return {"status": "ok"}
```

#### 全局单例

```python
# database/sync_debouncer.py 追加

_instance: Optional[SyncDebouncer] = None
_instance_lock = threading.Lock()

def get_sync_debouncer() -> SyncDebouncer:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = SyncDebouncer(delay=1.5)
    return _instance
```

#### SyncDebouncer + TaskRegistry 组合设计

去抖由 `SyncDebouncer` 处理（Timer 去抖），实际执行由 `TaskRegistry._executor` 线程池承载（避免 Timer 线程执行耗时网络 I/O 的资源回收问题）：

```python
# database/sync_debouncer.py — SyncDebouncer 只管计时去抖
debouncer.trigger(lambda: get_task_registry().submit(_do_sync))
```

- `SyncDebouncer.trigger()`：重置 1.5 秒计时器，取消前一个待执行的 timer
- `TaskRegistry.submit()`：将 `_do_sync` 提交到 `ThreadPoolExecutor(max_workers=4)`
- 连续快速保存 → 只有最后一个 timer 到期后提交一次 sync → 去抖生效

### 影响

- `PUT /api/words/{voc_id}` 响应后 ~1.5 秒完成云端同步
- 连续快速保存时自动合并为一次 sync（去抖核心价值）
- CLI 路径不受影响（仍走 sync daemon 的 5 秒去抖）
- 纯本地模式下 `do_sync_on()` 自动 no-op（hasattr 保护）

---

## 实施顺序建议

| 阶段 | 内容 | 风险 | 预估改动量 |
|------|------|------|-----------|
| **Phase 1** | 点 3：清理冗余探针 | 低 | 2 个文件，删除 ~12 行 |
| **Phase 2** | 点 4：Web 即时同步 | 低 | 新增 1 个文件，改动 1 个路由 |
| **Phase 3** | 点 1：锁下沉 — 先改 do_sync_on 调用点 | 中 | 5 个文件，~15 处改动 |
| **Phase 4** | 点 1：锁下沉 — 全面替换剩余调用点 | 高 | 15+ 文件，27+ 处改动，10+ 测试更新 |

**建议分阶段提交 PR，每阶段独立可测。**
