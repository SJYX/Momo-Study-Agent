# Backend 锁下沉 + 环境探针清理 + Web 即时同步 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将外部 conn_op_lock 全面下沉到 Backend 内部（libsql 保留锁，pyturso 零锁 MVCC）；清理冗余环境探针；Web UI 保存后 1.5 秒去抖即时云端同步。

**Architecture:** Backend 通过 `op_lock_for(conn)` context manager 暴露并发控制接口。LibsqlBackend 用 `_main_lock` + `_hub_lock` 双锁隔离，PytursoBackend 返回 no-op。Web 路由通过 SyncDebouncer + TaskRegistry 实现异步去抖同步。

**Tech Stack:** Python 3.12+, threading.Lock, contextlib.contextmanager, FastAPI, ThreadPoolExecutor (TaskRegistry)

---

## 独立性说明

三个子任务完全独立，可按任意顺序执行，每个都产生可测试的独立交付物：
- **Phase A**: 环境探针清理（2 个文件，纯删除）
- **Phase B**: Web 即时同步（1 个新文件 + 1 个路由改动）
- **Phase C**: 锁全面下沉（15+ 文件，27+ 调用点，高风险核心改动）

---

## Phase A: 清理冗余环境探针

### Task A1: 移除 _pyturso.py 冗余探针

**Files:**
- Modify: `database/backends/_pyturso.py:13-19`

- [ ] **Step 1: Read current code**

```python
# database/backends/_pyturso.py lines 13-19:
try:
    import turso.sync  # noqa: F401
    HAS_PYTURSO = True
except ImportError:
    HAS_PYTURSO = False
```

- [ ] **Step 2: Replace with import from集中源**

```python
# Replace lines 13-19 with:
from database.backends import HAS_PYTURSO
```

- [ ] **Step 3: Run tests to verify no regression**

```bash
python -m pytest tests/unit/database/backends/test_protocol.py -v --tb=short
```

Expected: all tests PASS (is_supported, Protocol compliance, no circular import)

- [ ] **Step 4: Commit**

```bash
git add database/backends/_pyturso.py
git commit -m "refactor: 移除 _pyturso.py 冗余 HAS_PYTURSO 探针，改用集中源导入"
```

### Task A2: 移除 _libsql.py 冗余探针

**Files:**
- Modify: `database/backends/_libsql.py:16-22`

- [ ] **Step 1: Read current code**

```python
# database/backends/_libsql.py lines 16-22:
try:
    import libsql
    HAS_LIBSQL = True
except ImportError:
    HAS_LIBSQL = False
```

- [ ] **Step 2: Replace with import from集中源**

```python
# Replace lines 16-22 with:
from database.backends import HAS_LIBSQL
```

- [ ] **Step 3: Run tests to verify no regression**

```bash
python -m pytest tests/unit/database/backends/test_protocol.py -v --tb=short
```

Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add database/backends/_libsql.py
git commit -m "refactor: 移除 _libsql.py 冗余 HAS_LIBSQL 探针，改用集中源导入"
```

### Task A3: 确认 V007 无冗余代码

**Files:**
- Read: `database/migrations/V007_migrate_db_format.py` (full file)

- [ ] **Step 1: Search for HAS_PYTURSO / HAS_LIBSQL in V007**

```bash
grep -n "HAS_PYTURSO\|HAS_LIBSQL" database/migrations/V007_migrate_db_format.py
```

Expected: no matches (确认无需改动)

- [ ] **Step 2: No commit needed (确认无改动)**

---

## Phase B: Web UI 即时同步 + 去抖

### Task B1: 创建 SyncDebouncer 模块

**Files:**
- Create: `database/sync_debouncer.py`

- [ ] **Step 1: Write the module**

```python
# database/sync_debouncer.py
"""去抖同步触发器：用户快速连续保存时合并为一次 sync。"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional


class SyncDebouncer:
    """N 秒空闲后执行一次回调。连续调用 trigger() 会重置计时器。"""

    def __init__(self, delay: float = 1.5) -> None:
        self._delay = delay
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def trigger(self, fn: Callable[[], None]) -> None:
        """重置去抖计时器。已有待执行 timer 则取消并重建。"""
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


# ── 全局单例 ──

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

- [ ] **Step 2: Write unit test**

```python
# tests/unit/database/test_sync_debouncer.py
"""SyncDebouncer 去抖逻辑测试。"""

import time
import threading

from database.sync_debouncer import SyncDebouncer


def test_debouncer_delays_execution():
    """debouncer 在 delay 秒后才执行回调。"""
    d = SyncDebouncer(delay=0.2)
    result = []
    d.trigger(lambda: result.append("fired"))
    assert result == []  # 尚未执行
    time.sleep(0.3)
    assert result == ["fired"]


def test_debouncer_cancels_previous():
    """连续 trigger 只执行最后一次。"""
    d = SyncDebouncer(delay=0.15)
    results = []
    d.trigger(lambda: results.append(1))
    time.sleep(0.05)
    d.trigger(lambda: results.append(2))  # 重置计时器
    time.sleep(0.25)
    assert results == [2]  # 第一次被取消


def test_debouncer_flush_executes_immediately():
    """flush 绕过去抖立即执行。"""
    d = SyncDebouncer(delay=10.0)  # 很长的 delay
    result = []
    d.trigger(lambda: result.append("delayed"))
    d.flush(lambda: result.append("flushed"))
    assert result == ["flushed"]  # flush 先于 delayed
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/unit/database/test_sync_debouncer.py -v --tb=short
```

Expected: all 3 tests PASS

- [ ] **Step 4: Commit**

```bash
git add database/sync_debouncer.py tests/unit/database/test_sync_debouncer.py
git commit -m "feat: 添加 SyncDebouncer 去抖模块 + 单元测试"
```

### Task B2: 修改 PUT /words 路由触发后台去抖同步

**Files:**
- Modify: `web/backend/routers/words.py:78-95`

- [ ] **Step 1: Read current PUT handler**

```python
# web/backend/routers/words.py lines 78-95:
@router.put("/{voc_id}")
@catch_api_errors("UPDATE_ERROR")
async def update_word_note(
    voc_id: str,
    body: dict,
    ctx = Depends(get_user_context),
):
    memory_aid = body.get("memory_aid", "")
    if not memory_aid:
        return error_response("INVALID_INPUT", "memory_aid 不能为空", user_id=ctx.profile_name)

    from database.word_repo import update_memory_aid

    ok = await run_in_threadpool(update_memory_aid, voc_id, memory_aid, db_path=ctx.db_path)
    if not ok:
        return error_response("UPDATE_ERROR", "更新 memory_aid 失败", user_id=ctx.profile_name)
    return ok_response({"updated": True, "voc_id": voc_id}, user_id=ctx.profile_name)
```

- [ ] **Step 2: Add background sync trigger after successful save**

Replace the return line (line 95) with the new code. Full handler after edit:

```python
@router.put("/{voc_id}")
@catch_api_errors("UPDATE_ERROR")
async def update_word_note(
    voc_id: str,
    body: dict,
    ctx = Depends(get_user_context),
):
    """编辑单词笔记的 memory_aid 字段。"""
    memory_aid = body.get("memory_aid", "")
    if not memory_aid:
        return error_response("INVALID_INPUT", "memory_aid 不能为空", user_id=ctx.profile_name)

    from database.word_repo import update_memory_aid

    ok = await run_in_threadpool(update_memory_aid, voc_id, memory_aid, db_path=ctx.db_path)
    if not ok:
        return error_response("UPDATE_ERROR", "更新 memory_aid 失败", user_id=ctx.profile_name)

    # 后台去抖触发云端同步（SyncDebouncer 计时 + TaskRegistry 线程池执行）
    try:
        from database.sync_debouncer import get_sync_debouncer
        from web.backend.tasks import get_task_registry
        from database.backends import get_active_backend
        from database.connection import _get_main_write_conn_singleton

        def _do_sync():
            conn = _get_main_write_conn_singleton()
            get_active_backend().do_sync_on(conn)

        get_sync_debouncer().trigger(
            lambda: get_task_registry().submit(_do_sync)
        )
    except Exception:
        pass  # 同步失败不回滚用户操作

    return ok_response({"updated": True, "voc_id": voc_id}, user_id=ctx.profile_name)
```

- [ ] **Step 3: Run existing web tests**

```bash
python -m pytest tests/web/test_words.py -v --tb=short
```

Expected: all existing tests still PASS (新增的同步代码被 try/except 包裹，不影响现有测试)

- [ ] **Step 4: Commit**

```bash
git add web/backend/routers/words.py
git commit -m "feat: PUT /words 成功后后台去抖触发云端同步（1.5s 去抖 + TaskRegistry）"
```

---

## Phase C: 锁全面下沉到 Backend 内部

> **风险等级：高。** 改动 15+ 文件，27+ 调用点。必须 TDD，每个 Task 后跑全量回归测试。

### Task C1: 扩展 TursoBackend Protocol，添加 `op_lock_for`

**Files:**
- Modify: `database/backends/_protocol.py`

- [ ] **Step 1: Read current Protocol**

```python
# database/backends/_protocol.py (current):
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class TursoBackend(Protocol):
    name: str
    def connect(self, db_path: str, url: str, token: str, *, do_sync: bool = False) -> Any: ...
    def do_sync_on(self, conn: Any) -> None: ...
    def is_supported(self) -> bool: ...
```

- [ ] **Step 2: Add op_lock_for to Protocol**

```python
# database/backends/_protocol.py (updated):
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Protocol, runtime_checkable


@runtime_checkable
class TursoBackend(Protocol):
    name: str

    @contextmanager
    def op_lock_for(self, conn: Any) -> Iterator[None]: ...

    def connect(
        self, db_path: str, url: str, token: str, *, do_sync: bool = False
    ) -> Any: ...

    def do_sync_on(self, conn: Any) -> None: ...

    def is_supported(self) -> bool: ...
```

- [ ] **Step 3: Run Protocol tests**

```bash
python -m pytest tests/unit/database/backends/test_protocol.py -v --tb=short
```

Expected: **FAIL** — existing backends don't have `op_lock_for` yet. This is expected.

- [ ] **Step 4: Commit**

```bash
git add database/backends/_protocol.py
git commit -m "feat(protocol): 扩展 TursoBackend Protocol，添加 op_lock_for context manager"
```

### Task C2: PytursoBackend 实现 op_lock_for（no-op）

**Files:**
- Modify: `database/backends/_pyturso.py`

- [ ] **Step 1: Add imports and method**

在 `PytursoBackend` class 定义开头（`name = "pyturso"` 之后）添加：

```python
from contextlib import contextmanager
# (如果文件顶部还没有 import)
```

在 `class PytursoBackend:` 内部，`name = "pyturso"` 之后，`is_supported` 之前添加：

```python
@contextmanager
def op_lock_for(self, conn: Any):
    """pyturso 引擎原生 MVCC，无需外部锁。"""
    yield
```

- [ ] **Step 2: Run Protocol tests**

```bash
python -m pytest tests/unit/database/backends/test_protocol.py -v --tb=short
```

Expected: all tests PASS (PytursoBackend 现在满足 Protocol)

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short -m "not slow"
```

Expected: all non-slow tests PASS

- [ ] **Step 4: Commit**

```bash
git add database/backends/_pyturso.py
git commit -m "feat(pyturso): 实现 op_lock_for（no-op context manager，MVCC 零锁开销）"
```

### Task C3: LibsqlBackend 实现 op_lock_for（双锁 + 动态分发）

**Files:**
- Modify: `database/backends/_libsql.py`
- Modify: `database/backends/_pyturso.py`（也在 connect() 中给 conn 打标签）

- [ ] **Step 1: 在 LibsqlBackend 中添加锁和 op_lock_for**

在 `database/backends/_libsql.py` 顶部添加导入：

```python
from contextlib import contextmanager
from typing import Any, Iterator  # 已有 Any, 追加 Iterator
```

在 `class LibsqlBackend:` 中，`name = "libsql"` 之后添加：

```python
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
    role = getattr(conn, "_momo_db_role", None)
    if role == "hub":
        return self._hub_lock
    return self._main_lock
```

- [ ] **Step 2: 在 connect() 中标记连接角色**

在 `database/backends/_libsql.py` 的 `connect()` 方法中，`return conn` 之前（约 line 283）添加：

```python
# 标记连接角色，供 op_lock_for 分发锁
conn._momo_db_role = "hub" if "hub" in os.path.basename(db_path).lower() else "main"
return conn
```

- [ ] **Step 3: 在 PytursoBackend.connect() 中也标记角色**

在 `database/backends/_pyturso.py` 的 `connect()` 方法中，`return db` 之前（约 line 213）添加：

```python
# 标记连接角色（统一接口，即使 pyturso 不需要锁）
db._momo_db_role = "hub" if "hub" in os.path.basename(db_path).lower() else "main"
return db
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/database/backends/test_protocol.py -v --tb=short
python -m pytest tests/ -v --tb=short -m "not slow"
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add database/backends/_libsql.py database/backends/_pyturso.py
git commit -m "feat(libsql): 实现双锁 op_lock_for（main_lock/hub_lock 动态分发）+ 连接角色标记"
```

### Task C4: 为 op_lock_for 编写单元测试

**Files:**
- Create: `tests/unit/database/backends/test_op_lock.py`

- [ ] **Step 1: Write tests**

```python
"""tests/unit/database/backends/test_op_lock.py: op_lock_for 单元测试。

验证:
- PytursoBackend.op_lock_for() 是 no-op（零开销）
- LibsqlBackend.op_lock_for() 对 main/hub 连接分发到不同锁
- 本地 sqlite3.Connection 被视为 main 角色
"""

import sqlite3
import threading
from contextlib import nullcontext

import pytest

from database.backends._libsql import LibsqlBackend
from database.backends._pyturso import PytursoBackend


def test_pyturso_op_lock_is_noop():
    """PytursoBackend.op_lock_for() 不获取任何锁，直接 yield。"""
    backend = PytursoBackend()
    conn = sqlite3.connect(":memory:")
    conn._momo_db_role = "main"

    # no-op context manager 不应阻塞
    with backend.op_lock_for(conn):
        pass  # 如果这里死锁，测试会超时

    conn.close()


def test_libsql_op_lock_main_and_hub_separate():
    """LibsqlBackend 的 main_lock 和 hub_lock 是独立的。"""
    backend = LibsqlBackend()

    main_conn = sqlite3.connect(":memory:")
    main_conn._momo_db_role = "main"
    hub_conn = sqlite3.connect(":memory:")
    hub_conn._momo_db_role = "hub"

    # main 和 hub 操作应互不阻塞
    barrier = threading.Barrier(2)

    def hold_main():
        with backend.op_lock_for(main_conn):
            barrier.wait(timeout=2.0)

    def hold_hub():
        with backend.op_lock_for(hub_conn):
            barrier.wait(timeout=2.0)

    t1 = threading.Thread(target=hold_main)
    t2 = threading.Thread(target=hold_hub)
    t1.start()
    t2.start()
    t1.join(timeout=3.0)
    t2.join(timeout=3.0)
    assert not t1.is_alive(), "main 线程应该已经完成"
    assert not t2.is_alive(), "hub 线程应该已经完成"

    main_conn.close()
    hub_conn.close()


def test_libsql_op_lock_main_serialized():
    """LibsqlBackend 的同一把 main_lock 应序列化并发操作。"""
    backend = LibsqlBackend()
    conn = sqlite3.connect(":memory:")
    conn._momo_db_role = "main"

    results = []

    def writer(val):
        with backend.op_lock_for(conn):
            results.append(val)

    t1 = threading.Thread(target=writer, args=(1,))
    t2 = threading.Thread(target=writer, args=(2,))
    t1.start()
    t2.start()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    # 由于是同一把锁，两个写入应完全有序
    assert len(results) == 2
    assert results in ([1, 2], [2, 1])
    conn.close()


def test_libsql_default_role_is_main():
    """没有 _momo_db_role 标记的连接默认走 main_lock。"""
    backend = LibsqlBackend()
    conn = sqlite3.connect(":memory:")
    # 不设置 _momo_db_role

    # 应不抛异常，走 main_lock 分支
    with backend.op_lock_for(conn):
        pass

    conn.close()
```

- [ ] **Step 2: Run tests**

```bash
python -m pytest tests/unit/database/backends/test_op_lock.py -v --tb=short
```

Expected: all 4 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/database/backends/test_op_lock.py
git commit -m "test: 添加 op_lock_for 单元测试（no-op / 双锁隔离 / 序列化 / 默认角色）"
```

### Task C5: 改写 execution_engine.py 中的锁调用

**Files:**
- Modify: `database/execution_engine.py:130-208` (`_execute_batch_writes`)
- Modify: `database/execution_engine.py:292-317` (`_sync_daemon`)

- [ ] **Step 1: 改写 _execute_batch_writes**

**Before** (lines 130-146):
```python
def _execute_batch_writes(write_conn: Any, batch: List[Dict[str, Any]]) -> None:
    if not batch:
        return
    max_retries = 3
    retry_count = 0
    last_error = None
    conn_lock = _get_singleton_conn_op_lock(write_conn)
    started_at = time.time()

    while retry_count < max_retries:
        try:
            if conn_lock is None:
                _execute_batch_writes_unlocked(write_conn, batch)
            else:
                with conn_lock:
                    _execute_batch_writes_unlocked(write_conn, batch)
```

**After:**
```python
def _execute_batch_writes(write_conn: Any, batch: List[Dict[str, Any]]) -> None:
    if not batch:
        return
    max_retries = 3
    retry_count = 0
    last_error = None
    started_at = time.time()

    while retry_count < max_retries:
        try:
            with get_active_backend().op_lock_for(write_conn):
                _execute_batch_writes_unlocked(write_conn, batch)
```

需要在文件顶部添加：
```python
from database.backends import get_active_backend
```

（如果还没有 import）

- [ ] **Step 2: 改写 _sync_daemon**

**Before** (lines 303-317):
```python
            conn = _get_main_write_conn_singleton(do_sync=False)
            conn_lock = _get_singleton_conn_op_lock(conn)
            sync_started_at = time.time()
            set_db_syncing(phase="idle_sync")

            if conn_lock is not None:
                with conn_lock:
                    get_active_backend().do_sync_on(conn)
            else:
                get_active_backend().do_sync_on(conn)
```

**After:**
```python
            conn = _get_main_write_conn_singleton(do_sync=False)
            sync_started_at = time.time()
            set_db_syncing(phase="idle_sync")

            with get_active_backend().op_lock_for(conn):
                get_active_backend().do_sync_on(conn)
```

- [ ] **Step 3: Remove unused _get_singleton_conn_op_lock import if no longer needed**

```bash
grep -n "_get_singleton_conn_op_lock" database/execution_engine.py
```

如果只有上面两处引用且都已移除，删除对应的 import。

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/ -v --tb=short -m "not slow"
```

Expected: all non-slow tests PASS

- [ ] **Step 5: Commit**

```bash
git add database/execution_engine.py
git commit -m "refactor(execution_engine): _execute_batch_writes 和 _sync_daemon 改用 backend.op_lock_for()"
```

### Task C6: 改写 sync_service.py 中的锁调用

**Files:**
- Modify: `database/sync_service.py:49` (function signature)
- Modify: `database/sync_service.py:100-109` (锁调用)
- Modify: `database/sync_service.py:171` (sync_databases 调用)
- Modify: `database/sync_service.py:215` (sync_hub_databases 调用)

- [ ] **Step 1: 修改 _run_libsql_sync_pipeline 函数签名**

**Before** (line 49):
```python
def _run_libsql_sync_pipeline(
    *,
    creds_ok: bool,
    creds_skip_reason: str,
    conn_factory: Callable[[], Any],
    conn_op_lock: Any,
    dry_run: bool = False,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    messages: Dict[str, str],
    skip_reason_local_only: str,
) -> Dict[str, Any]:
```

**After** — 移除 `conn_op_lock` 参数：
```python
def _run_libsql_sync_pipeline(
    *,
    creds_ok: bool,
    creds_skip_reason: str,
    conn_factory: Callable[[], Any],
    dry_run: bool = False,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    messages: Dict[str, str],
    skip_reason_local_only: str,
) -> Dict[str, Any]:
```

- [ ] **Step 2: 修改 _do_sync 内部锁调用**

**Before** (lines 100-109):
```python
            def _do_sync():
                try:
                    _backend = get_active_backend()
                    if conn_op_lock is not None:
                        with conn_op_lock:
                            _backend.do_sync_on(conn)
                    else:
                        _backend.do_sync_on(conn)
                    sync_result_box[0] = True
```

**After:**
```python
            def _do_sync():
                try:
                    _backend = get_active_backend()
                    with _backend.op_lock_for(conn):
                        _backend.do_sync_on(conn)
                    sync_result_box[0] = True
```

- [ ] **Step 3: 修改 sync_databases 调用**

**Before** (line 171):
```python
    return _run_libsql_sync_pipeline(
        ...
        conn_op_lock=connection._main_write_conn_op_lock,
        ...
    )
```

**After** — 删除 `conn_op_lock=connection._main_write_conn_op_lock,` 这一行。

- [ ] **Step 4: 修改 sync_hub_databases 调用**

同上，删除 `conn_op_lock=connection._hub_write_conn_op_lock,` 这一行。

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/ -v --tb=short -m "not slow"
```

Expected: all non-slow tests PASS（可能需要更新 `tests/unit/database/test_sync_service_skip_paths.py` 中的 `_NullLock()` 参数）

- [ ] **Step 6: Commit**

```bash
git add database/sync_service.py
git commit -m "refactor(sync_service): 移除 conn_op_lock 参数，改用 backend.op_lock_for()"
```

### Task C7: 改写 connection.py 中的锁调用

**Files:**
- Modify: `database/connection.py:420-430` (main health check)
- Modify: `database/connection.py:494-500` (hub health check)
- Modify: `database/connection.py:740-760` (`_run_with_managed_connection`)
- Modify: `database/connection.py:795-825` (`_hub_fetch_one_dict`)
- Modify: `database/connection.py:845-875` (`_hub_fetch_all_dicts`)
- Delete: `database/connection.py:126` (`_main_write_conn_op_lock`)
- Delete: `database/connection.py:131` (`_hub_write_conn_op_lock`)
- Delete: `database/connection.py:280-285` (`_get_singleton_conn_op_lock`)

- [ ] **Step 1: Modify health check functions**

**Main health check** (`_get_main_write_conn_singleton`, ~line 422):

**Before:**
```python
            with _main_write_conn_op_lock:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                _get_backend().do_sync_on(conn)
```

**After:**
```python
            with get_active_backend().op_lock_for(conn):
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                get_active_backend().do_sync_on(conn)
```

（注意：`_get_backend()` 在 connection.py 中是本地函数，等同于 `get_active_backend()`。保持用 `_get_backend()` 以减少 diff）

**Hub health check** (~line 496): 同样模式。

- [ ] **Step 2: Modify _run_with_managed_connection** (~line 745)

**Before:**
```python
    conn_lock = _get_singleton_conn_op_lock(target_conn)
    ...
    if conn_lock is not None:
        with conn_lock:
            result = operation(target_conn)
            if owned:
                target_conn.commit()
    else:
        result = operation(target_conn)
        if owned:
            target_conn.commit()
```

**After:**
```python
    with get_active_backend().op_lock_for(target_conn):
        result = operation(target_conn)
        if owned:
            target_conn.commit()
```

- [ ] **Step 3: Modify _hub_fetch_one_dict** (~line 799)

**Before:**
```python
    conn_lock = _get_singleton_conn_op_lock(hub_conn)
    ...
    if conn_lock is not None:
        with conn_lock:
            cur = hub_conn.cursor()
            ...
    else:
        cur = hub_conn.cursor()
        ...
    if conn_lock is None:
        hub_conn.close()
```

**After:**
```python
    is_singleton = _is_hub_write_singleton_conn(hub_conn)
    if not is_singleton:
        try:
            cur = hub_conn.cursor()
            cur.execute(sql, params or ())
            row = cur.fetchone()
            cur.close()
            return dict(row) if row else None
        finally:
            hub_conn.close()
    else:
        with get_active_backend().op_lock_for(hub_conn):
            cur = hub_conn.cursor()
            cur.execute(sql, params or ())
            row = cur.fetchone()
            cur.close()
            return dict(row) if row else None
```

（保留 singleton 检查来决定是否 close 连接，但锁获取改为 backend.op_lock_for）

- [ ] **Step 4: Modify _hub_fetch_all_dicts** (~line 849)

与 `_hub_fetch_one_dict` 同样模式。

- [ ] **Step 5: 删除旧锁定义和路由函数**

删除：
- Line 126: `_main_write_conn_op_lock = threading.Lock()`
- Line 131: `_hub_write_conn_op_lock = threading.Lock()`
- Lines 280-285: `_get_singleton_conn_op_lock()` 函数

保留 `_is_main_write_singleton_conn()` 和 `_is_hub_write_singleton_conn()` — 仍被其他代码使用（如 singleton close 判断）。

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/ -v --tb=short -m "not slow"
```

Expected: most tests PASS, but tests that mock `_get_singleton_conn_op_lock` will fail. Fix in next task.

- [ ] **Step 7: Commit**

```bash
git add database/connection.py
git commit -m "refactor(connection): 锁调用下沉到 backend.op_lock_for，删除 _main/hub_write_conn_op_lock 和 _get_singleton_conn_op_lock"
```

### Task C8: 改写 session.py 中的锁调用

**Files:**
- Modify: `database/session.py:36-65` (`DBSession.__init__` + `_acquire_read_lock`)
- Modify: `database/session.py:187` (`with_read_session`)
- Modify: `database/session.py:252` (`with_write_session`)

- [ ] **Step 1: 简化 DBSession**

DBSession 当前接受外部 `lock` 参数并管理 acquire/release。改为直接接受 backend 引用：

**Before** (lines 22-65):
```python
class DBSession:
    DEFAULT_READ_LOCK_TIMEOUT = 2.0

    def __init__(self, conn: Any, lock: Any = None, lock_timeout: float = DEFAULT_READ_LOCK_TIMEOUT):
        self.conn = conn
        self.lock = lock
        self.lock_timeout = lock_timeout

    def _acquire_read_lock(self) -> bool:
        if self.lock is None:
            return False
        is_singleton = connection._is_main_write_singleton_conn(self.conn) or connection._is_hub_write_singleton_conn(self.conn)
        if is_singleton:
            self.lock.acquire()
            return True
        acquired = self.lock.acquire(timeout=self.lock_timeout)
        ...
```

**After:**
```python
class DBSession:
    def __init__(self, conn: Any, backend: Any = None):
        self.conn = conn
        self._backend = backend

    @contextmanager
    def _lock_context(self):
        if self._backend is not None:
            with self._backend.op_lock_for(self.conn):
                yield
        else:
            yield
```

`fetchall`、`fetchone`、`execute`、`executemany` 全部改为使用 `_lock_context()`：

```python
    def fetchall(self, sql: str, params: tuple = ()) -> List[Any]:
        with self._lock_context():
            cur = self.conn.cursor()
            try:
                cur.execute(sql, params)
                return cur.fetchall()
            finally:
                cur.close()

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[Any]:
        with self._lock_context():
            cur = self.conn.cursor()
            try:
                cur.execute(sql, params)
                return cur.fetchone()
            finally:
                cur.close()

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock_context():
            cur = self.conn.cursor()
            try:
                cur.execute(sql, params)
            finally:
                cur.close()
            self.conn.commit()

    def executemany(self, sql: str, params_list: List[tuple]) -> None:
        with self._lock_context():
            cur = self.conn.cursor()
            try:
                cur.executemany(sql, params_list)
            finally:
                cur.close()
            self.conn.commit()
```

- [ ] **Step 2: 修改 with_read_session 和 with_write_session**

**Before** (line 187):
```python
                conn_lock = connection._get_singleton_conn_op_lock(c)
                session = DBSession(c, conn_lock)
```

**After:**
```python
                from database.backends import get_active_backend
                session = DBSession(c, backend=get_active_backend())
```

（`with_write_session` line 252 同样修改）

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/ -v --tb=short -m "not slow"
```

Expected: tests that depend on DBSession lock behavior may need updating.

- [ ] **Step 4: Commit**

```bash
git add database/session.py
git commit -m "refactor(session): DBSession 改用 backend.op_lock_for() context manager"
```

### Task C9: 改写剩余调用点

**Files:**
- Modify: `database/notes_repo.py:487-499`
- Modify: `database/community_lookup.py:66, 169-170`
- Modify: `database/schema.py:284, 318, 403-407, 455-456`
- Modify: `core/weak_word_filter.py:136-140`
- Modify: `core/iteration_manager.py:162-166, 336-340`
- Modify: `web/backend/routers/stats.py:37, 128, 149`
- Modify: `web/backend/routers/ops.py:118`

每个文件的改写模式相同：

**Before:**
```python
conn_lock = connection._get_singleton_conn_op_lock(c)
if conn_lock is not None:
    with conn_lock:
        # ... operation ...
else:
    # ... operation ...
```

**After:**
```python
with get_active_backend().op_lock_for(c):
    # ... operation ...
```

（对于 `community_lookup.py` 的 `_safe_cursor(lock=...)`，移除 lock 参数，改为内部调用 backend.op_lock_for）

- [ ] **Step 1: database/notes_repo.py**

修改 `atomic_save_iteration_and_update_note` 函数中的锁调用。

- [ ] **Step 2: database/community_lookup.py**

修改 `_safe_cursor` 和 `_fetch_notes_from_current_db` 中的锁调用。

- [ ] **Step 3: database/schema.py**

修改 `init_db()`、`init_hub_db()` 中的直接 `_main_write_conn_op_lock` 和 `_hub_write_conn_op_lock` 引用。

修改 `apply_migrations(lock=...)` 调用 — 移除 `lock` 参数。

- [ ] **Step 4: database/migrations/runner.py**

从 `apply_migrations(conn, lock=None)` 移除 `lock` 参数。内部改为 `with get_active_backend().op_lock_for(conn):`。

- [ ] **Step 5: core/weak_word_filter.py**

修改 `_get_user_stats` 中的锁调用。

- [ ] **Step 6: core/iteration_manager.py**

修改 `_get_last_recorded_fam` 和 `_record_level_change` 中的锁调用。

- [ ] **Step 7: web/backend/routers/stats.py**

修改 `_fetch_summary_data`、`_fetch_ops_db_data` 中的锁调用。

- [ ] **Step 8: web/backend/routers/ops.py**

修改 `/api/ops/status` 中的锁调用。

- [ ] **Step 9: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short -m "not slow"
```

Expected: all tests PASS

- [ ] **Step 10: Commit**

```bash
git add database/notes_repo.py database/community_lookup.py database/schema.py database/migrations/runner.py core/weak_word_filter.py core/iteration_manager.py web/backend/routers/stats.py web/backend/routers/ops.py
git commit -m "refactor: 全面替换剩余 16 个调用点，改用 backend.op_lock_for()"
```

### Task C10: 更新测试中的 mock 代码

**Files:**
- Modify: `tests/core/test_weak_word_filter.py:83`
- Modify: `tests/web/test_words.py:15`
- Modify: `tests/web/test_stats.py:20,63,86`
- Modify: `tests/web/test_sync.py:15,29,50,88,101`
- Modify: `tests/unit/database/test_read_conn_isolation.py:71,205`
- Modify: `tests/unit/database/test_sync_service_skip_paths.py:51,77,112,141`

- [ ] **Step 1: 搜索所有 mock _get_singleton_conn_op_lock 的测试**

```bash
grep -rn "_get_singleton_conn_op_lock\|_main_write_conn_op_lock\|_hub_write_conn_op_lock" tests/
```

- [ ] **Step 2: 逐个更新每个测试文件**

将 `monkeypatch.setattr(..., "_get_singleton_conn_op_lock", ...)` 替换为 mock backend 的 `op_lock_for` 方法。

**Before** (example from test_sync.py):
```python
monkeypatch.setattr(connection, "_get_singleton_conn_op_lock", lambda conn: _NullLock())
```

**After:**
```python
from unittest.mock import MagicMock
mock_backend = MagicMock()
mock_backend.op_lock_for.return_value = contextlib.nullcontext()
monkeypatch.setattr("database.backends.get_active_backend", lambda: mock_backend)
```

- [ ] **Step 3: 更新 test_sync_service_skip_paths.py**

该测试传递 `_NullLock()` 作为 `conn_op_lock` 参数。由于 `_run_libsql_sync_pipeline` 不再接受此参数，删除相关参数。

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short -m "not slow"
```

Expected: all non-slow tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: 更新所有测试中的锁 mock，适配 backend.op_lock_for() 新接口"
```

### Task C11: 删除死代码 + 最终回归测试

**Files:**
- Verify: `database/connection.py` — 确认 `_get_singleton_conn_op_lock`, `_main_write_conn_op_lock`, `_hub_write_conn_op_lock` 已删除
- Verify: 所有引用 `_get_singleton_conn_op_lock` 的代码已清除

- [ ] **Step 1: 最终 grep 确认无残留**

```bash
grep -rn "_get_singleton_conn_op_lock\|_main_write_conn_op_lock\|_hub_write_conn_op_lock" database/ core/ web/
```

Expected: no matches (除了可能的注释或文档引用)

- [ ] **Step 2: Full regression test**

```bash
python -m pytest tests/ -v --tb=short -m "not slow"
```

Expected: all non-slow tests PASS

- [ ] **Step 3: Run syntax check on changed files**

```bash
python -m py_compile database/backends/_protocol.py
python -m py_compile database/backends/_pyturso.py
python -m py_compile database/backends/_libsql.py
python -m py_compile database/connection.py
python -m py_compile database/execution_engine.py
python -m py_compile database/sync_service.py
python -m py_compile database/session.py
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "cleanup: 删除 _get_singleton_conn_op_lock 和外部 op_lock 死代码"
```

---

## Phase C 总结

Phase C 完成后，整个代码库的并发控制从"外部 conn_op_lock 分散管理"迁移为"Backend 内部 op_lock_for 自管理"：

| 变化 | 之前 | 之后 |
|------|------|------|
| 锁定义 | `connection.py` 中 `_main_write_conn_op_lock` / `_hub_write_conn_op_lock` | `LibsqlBackend` 内部 `_main_lock` / `_hub_lock` |
| 锁获取 | `_get_singleton_conn_op_lock(conn)` + `if/else` | `backend.op_lock_for(conn)` — 一行搞定 |
| pyturso | 路径被外部锁串行化 | 零锁，MVCC 全并发 |
| libsql | 锁在外部，backend 不自包含 | 锁在内部，backend 自包含 |
| 测试 | mock `_get_singleton_conn_op_lock` | mock `backend.op_lock_for` |
