# Close-Guard 下沉到 Backend 设计文档

> 日期: 2026-05-21
> 背景: ~19 个 `_is_main_write_singleton_conn(conn)` / `_is_hub_write_singleton_conn(conn)` close-guard 调用点散布在 10 个文件中。这些检查纯粹是因为 libsql 的单写连接约束 — pyturso MVCC 不需要。目标是将 `should_close(conn)` 逻辑下沉到 Backend，调用点只写一行。

---

## 核心设计：Backend 内部记账（id() 集合）

### 为什么不能直接打属性（AttributeError 陷阱）

`sqlite3.Connection`、`turso.sync` 连接、`libsql` 连接底层都是 C/Rust 扩展对象，**通常没有 `__dict__` 槽位**，动态赋值 `conn._is_momo_singleton = True` 会抛 `AttributeError` 并导致启动崩溃。

因此改用 Backend 内部维护单例连接的 `id()` 集合：

```python
class PytursoBackend:
    def __init__(self):
        self._singleton_ids: set[int] = set()

    def connect(self, db_path, url, token, *, do_sync=False, is_singleton=False):
        conn = turso.sync.connect(...)
        if is_singleton:
            self._singleton_ids.add(id(conn))
        return conn

    def should_close(self, conn: Any) -> bool:
        return id(conn) not in self._singleton_ids
```

两个 Backend 实现完全相同。`connect()` 新增 `is_singleton=False` 参数，由 connection.py 在创建单例连接时传入 `True`。

---

## TursoBackend Protocol 扩展

```python
# database/backends/_protocol.py
@runtime_checkable
class TursoBackend(Protocol):
    name: str

    @contextmanager
    def op_lock_for(self, conn: Any) -> Iterator[None]: ...

    def should_close(self, conn: Any) -> bool: ...  # ← 新增

    def connect(
        self, db_path: str, url: str, token: str,
        *, do_sync: bool = False, is_singleton: bool = False,  # ← is_singleton 新增
    ) -> Any: ...
    def do_sync_on(self, conn: Any) -> None: ...
    def is_supported(self) -> bool: ...
```

---

## Backend 实现（两个 backend 完全相同）

```python
class PytursoBackend:  # LibsqlBackend 同
    def __init__(self):
        self._singleton_ids: set[int] = set()

    def connect(self, db_path, url, token, *, do_sync=False, is_singleton=False):
        conn = ...  # 原有连接创建逻辑
        if is_singleton:
            self._singleton_ids.add(id(conn))
        return conn

    def should_close(self, conn: Any) -> bool:
        """非单例连接可安全关闭；单例连接由 backend 管理生命周期。"""
        return id(conn) not in self._singleton_ids
```

**单例生命周期贯穿进程，`_singleton_ids` 中的引用不会泄漏。** 连接关闭后 `id()` 可能被复用，但 singleton 关闭后整个进程会退出或重建 backend 实例，不构成问题。

---

## connection.py 改动：传入 is_singleton=True

需要在 2 处 singleton 创建时传入标记：

| 位置 | 改动 |
|------|------|
| `_get_main_write_conn_singleton` (~line 451) | `backend.connect(..., is_singleton=True)` |
| `_get_hub_write_conn_singleton` (~line 517) | `backend.connect(..., is_singleton=True)` |

---

## 调用点替换模板

**Before:**
```python
if not connection._is_main_write_singleton_conn(c):
    c.close()
```

**After:**
```python
from database.backends import get_active_backend
if get_active_backend().should_close(c):
    c.close()
```

或者如果已经有 `_backend` 变量：
```python
if _backend.should_close(c):
    c.close()
```

---

## 需改动的调用点清单（~19 处）

> `database/execution_engine.py` 中的 `_mark_main_db_needs_sync` 也引用了 `_is_main_write_singleton_conn`，语义与 `not should_close(conn)` 重合，一并替换以确保删除函数定义后无残留。

### database/session.py (4 处)
- `with_read_session` except handler (~line 161)
- `with_read_session` finally block (~line 183)
- `with_write_session` finally block (~line 225)
- `_attempt_auto_recovery` (~line 96)

### database/connection.py (3 处)
- `_run_with_managed_connection` (~line 746) — 合并 main + hub 检查为 `should_close`
- `_hub_fetch_one_dict` (~line 793) — 简化为 `_get_backend().should_close(hub_conn)`
- `_hub_fetch_all_dicts` (~line 833) — 同上

### database/execution_engine.py (1 处)
- `_mark_main_db_needs_sync` (~line 426) — `if connection._is_main_write_singleton_conn(conn)` → `if not get_active_backend().should_close(conn)`

### database/community_lookup.py (1 处)
- `find_words_in_community_batch` (~line 175)

### database/notes_repo.py (1 处)
- `atomic_save_iteration_and_update_note` (~line 551)

### database/momo_words.py (1 处)
- `log_test_run` (~line 199)

### database/schema.py (2 处)
- `init_users_hub_tables` early-exit (~line 393) — `_is_hub_write_singleton_conn`
- `init_users_hub_tables` after DDL (~line 454) — `_is_hub_write_singleton_conn`

### core/iteration_manager.py (2 处)
- `_get_last_recorded_fam` (~line 171)
- `_update_it_state` (~line 334)

### core/weak_word_filter.py (1 处)
- `_get_user_stats` (~line 161)

### web/backend/routers/stats.py (3 处)
- `_fetch_summary_data` (~line 69)
- `_fetch_ops_db_data` (~line 114, ~line 134)

### web/backend/routers/ops.py (1 处)
- `db_replica_health` (~line 127)

---

## 可删除的代码

完成替换后，以下代码变为死代码：

- `database/connection.py` 中的 `_is_main_write_singleton_conn()` 函数定义 (~line 268)
- `database/connection.py` 中的 `_is_hub_write_singleton_conn()` 函数定义 (~line 273)
- 所有 `from database.connection import ..._is_main_write_singleton_conn` 的 import

**注意：** `_main_write_conn_singleton` 和 `_hub_write_conn_singleton` 全局变量仍需保留 — 它们被 `_get_main_write_conn_singleton()` 和 `_get_hub_write_conn_singleton()` 内部使用（赋值、读取、健康检查）。只是外部调用点不再需要检查它们。

---

## 测试更新

测试中 mock `_is_main_write_singleton_conn` 的地方需要更新为 mock `backend.should_close`：

- `tests/web/test_words.py` — 已有 `mock_backend` pattern，只需加 `mock_backend.should_close.return_value = True`
- `tests/web/test_sync.py` — 同上
- `tests/web/test_stats.py` — 同上
- `tests/core/test_weak_word_filter.py` — 同上
- `tests/unit/database/test_read_conn_isolation.py` — 用 `backend.should_close(conn)` 替代断言
- `tests/unit/database/test_session_lock_timeout.py` — 已重写，可能需要适配

---

## 风险与注意事项

1. **`id()` 复用风险（极低）**: Python 对象被 GC 后 `id()` 可能被复用给新对象。但由于 singleton 连接的生命周期贯穿整个进程，且 `_singleton_ids` 通过 `connect(is_singleton=True)` 注册，不会出现 id 复用导致的误判。仅在极端场景（进程不退出但 backend 实例被销毁重建）下可能有问题 — 但此时整个连接池都会重建，不是问题。

2. **`is_singleton` 参数传递**: 必须在 `connection.py` 中 `backend.connect()` 调用处传入 `is_singleton=True`。如果遗漏，`should_close()` 对该 singleton 连接会错误返回 `True`，导致被外部误关。这是一个静默错误（不会 crash，但会导致 singleton 被重建）。

3. **本地连接安全**: `_get_local_conn()` 和 `_get_local_read_conn()` 创建的连接不经过 `backend.connect()`，`_singleton_ids` 中没有它们的 id。`should_close()` 对它们返回 `True`（正确 — 应该关闭）。

4. **Protocol 签名变更**: `connect()` 新增 `is_singleton=False` keyword-only 参数。由于是 keyword-only 且有默认值，对现有代码透明。但如果外部直接调用 `backend.connect()`（非通过 connection.py singleton getter），不会自动注册为 singleton。

5. **向后兼容**: `_is_main_write_singleton_conn` 和 `_is_hub_write_singleton_conn` 删除后，所有外部引用通过 `backend.should_close()` 替代。`execution_engine.py` 的 `_mark_main_db_needs_sync` 也一并迁移，确保无孤立调用。
