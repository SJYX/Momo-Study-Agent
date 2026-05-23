# Phase 2: 移除死壳队列 + 收敛写 API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除 `_queue_write_operation` / `_queue_batch_write_operation` 两个永远 return False 的死壳函数;把 `init_concurrent_system` / `cleanup_concurrent_system` 重命名为 `init_db_session_resources` / `cleanup_db_session_resources`(因为已经不存在"并发系统",只是连接生命周期管理);刷新 `_execute_*_sync`、`_db_syncing`、`_get_dedicated_write_conn` 的 docstring 以表达 pyturso-native 意图。**write singleton 保留**,只刷新它的角色描述。

**Architecture:** 5 个独立提交,从 Phase 1 合并后的 `feat/web-ui` 切出 `refactor/libsql-cleanup-phase2` 分支。先删死壳,后做重命名,最后是 docstring 刷新 + 验证。

**Tech Stack:** Python 3.12+, pytest, git。无新依赖。

**Reference:** [`docs/superpowers/specs/2026-05-23-libsql-residual-cleanup-design.md`](../specs/2026-05-23-libsql-residual-cleanup-design.md) Phase 2 section.

**Prerequisite:** Phase 1 PR 已 merge 回 `feat/web-ui`。

---

## Task 1: 分支准备

**Files:**
- 无文件修改, 仅 git 操作

- [ ] **Step 1: 切回 feat/web-ui 拉最新 (确保已包含 Phase 1)**

```bash
git checkout feat/web-ui
git pull --ff-only
```

Expected: fast-forward 包含 Phase 1 的 6 个 commits。

- [ ] **Step 2: 确认 Phase 1 已落地**

```bash
git log --oneline -10 | Select-String "libsql-cleanup-phase1|chore.database.*libsql"
```

Expected: 至少能看到 Phase 1 的合并 commit 或它的 squash commit。

- [ ] **Step 3: 切出 Phase 2 工作分支**

```bash
git checkout -b refactor/libsql-cleanup-phase2
```

Expected: `Switched to a new branch 'refactor/libsql-cleanup-phase2'`

---

## Task 2: 删除 `_queue_*` 死壳函数 + 清理 re-export

**Files:**
- Modify: `database/execution_engine.py:66-73` (delete two functions)
- Modify: `database/connection.py:736-737` (remove from re-export)

- [ ] **Step 1: 确认 `_queue_*` 调用方仅 1 个测试**

```bash
git grep -l "_queue_write_operation\|_queue_batch_write_operation"
```

Expected output(且仅这 3 个文件):
```
database/execution_engine.py
database/connection.py
tests/unit/database/test_dispatch_paths.py
```

如有第 4 个文件 → STOP, 评估再继续。

- [ ] **Step 2: 删除 `database/execution_engine.py` 中两个空壳函数**

定位行 66-73:
```python
def _queue_write_operation(sql: str, args: Tuple = (), op_type: str = "insert_or_replace", db_path: Optional[str] = None) -> bool:
    """入队单条写操作。已弃用，因为在 pyturso 下所有写入同步直写。"""
    return False


def _queue_batch_write_operation(sql: str, args_list: List[Tuple], db_path: Optional[str] = None) -> bool:
    """入队批量写操作。已弃用，因为在 pyturso 下所有写入同步直写。"""
    return False
```

**完全删除**这 8 行(包括上下空行)。

- [ ] **Step 3: 删除 `database/connection.py` 末尾 re-export 列表中的两个名字**

定位文件末尾(约 732-742 行)的 re-export block:
```python
# Re-exported for external consumers:
#   - database/_repo_helpers.py accesses 4 names via connection.X
#   - core/study_flow.py imports init_concurrent_system / cleanup_concurrent_system
from database.execution_engine import (
    _queue_write_operation,
    _queue_batch_write_operation,
    _execute_write_sql_sync,
    _execute_batch_write_sql_sync,
    init_concurrent_system,
    cleanup_concurrent_system,
)
```

把 `_queue_write_operation,` 和 `_queue_batch_write_operation,` 两行**删除**。同时更新顶部注释里"4 names via connection.X"为"2 names via connection.X"(因为剩 `_execute_write_sql_sync` 和 `_execute_batch_write_sql_sync` 两个)。

最终该 block 应该是:
```python
# Re-exported for external consumers:
#   - database/_repo_helpers.py accesses 2 names via connection.X
#   - core/study_flow.py imports init_concurrent_system / cleanup_concurrent_system
from database.execution_engine import (
    _execute_write_sql_sync,
    _execute_batch_write_sql_sync,
    init_concurrent_system,
    cleanup_concurrent_system,
)
```

- [ ] **Step 4: 验证 import 不破**

```bash
python -m py_compile database/execution_engine.py database/connection.py
python -c "from database.connection import _execute_write_sql_sync, _execute_batch_write_sql_sync; print('imports ok')"
```

Expected: `imports ok`

- [ ] **Step 5: 更新 `tests/unit/database/test_dispatch_paths.py` (删除 queue 相关 fixture)**

打开 `tests/unit/database/test_dispatch_paths.py`,做以下三处编辑:

5a. **顶部 docstring 改述** (行 1-7):
```python
"""tests/unit/database/test_dispatch_paths.py: 双写路径（本地直写 vs 队列）一致性与异常恢复。

通过 monkeypatch database.connection 内部函数，验证：
- 当 _should_use_local_only_connection 返回 True 时走本地同步执行
- 否则走队列入队
- 写入失败异常被 repo 层吞错并返回 False，且不向上抛
"""
```
→
```python
"""tests/unit/database/test_dispatch_paths.py: 写入路径一致性与异常恢复。

通过 monkeypatch database.connection 内部函数，验证：
- 所有写入都走本地同步执行 (_execute_write_sql_sync)
- 写入失败异常被 repo 层吞错并返回 False，且不向上抛

Pre-pyturso 时代曾有"双写路径"（本地直写 vs 队列）一致性检验,在 pyturso
统一为同步直写后,队列相关 fixture/断言已移除。
"""
```

5b. **`fake_dispatch` fixture 内删除 queue 相关代码** (行 24-52):

定位整个 `@pytest.fixture` `def fake_dispatch(...)`:

```python
@pytest.fixture
def fake_dispatch(monkeypatch):
    """记录每次写入分发的去向（local-direct vs queue）。"""
    calls = {"local_single": 0, "local_batch": 0, "queue_single": 0, "queue_batch": 0}

    def fake_local_only(db_path, conn):
        # 测试默认走本地直写路径
        return True

    def fake_exec_sync(sql, args, *, db_path=None, conn=None):
        calls["local_single"] += 1

    def fake_batch_sync(sql, args_list, *, db_path=None, conn=None):
        calls["local_batch"] += 1

    def fake_queue(sql, args, op_type="insert_or_replace"):
        calls["queue_single"] += 1
        return True

    def fake_queue_batch(sql, args_list):
        calls["queue_batch"] += 1
        return True

    monkeypatch.setattr(conn_mod, "_should_use_local_only_connection", fake_local_only)
    monkeypatch.setattr(conn_mod, "_execute_write_sql_sync", fake_exec_sync)
    monkeypatch.setattr(conn_mod, "_execute_batch_write_sql_sync", fake_batch_sync)
    monkeypatch.setattr(conn_mod, "_queue_write_operation", fake_queue)
    monkeypatch.setattr(conn_mod, "_queue_batch_write_operation", fake_queue_batch)
    return calls
```

→ 简化为:
```python
@pytest.fixture
def fake_dispatch(monkeypatch):
    """记录每次写入分发的去向（local-direct only after pyturso migration）。"""
    calls = {"local_single": 0, "local_batch": 0}

    def fake_local_only(db_path, conn):
        return True

    def fake_exec_sync(sql, args, *, db_path=None, conn=None):
        calls["local_single"] += 1

    def fake_batch_sync(sql, args_list, *, db_path=None, conn=None):
        calls["local_batch"] += 1

    monkeypatch.setattr(conn_mod, "_should_use_local_only_connection", fake_local_only)
    monkeypatch.setattr(conn_mod, "_execute_write_sql_sync", fake_exec_sync)
    monkeypatch.setattr(conn_mod, "_execute_batch_write_sql_sync", fake_batch_sync)
    return calls
```

5c. **两个测试函数中删除 queue 断言**

第一个 (`test_dispatch_write_always_uses_local_path`,行 55-67):
```python
def test_dispatch_write_always_uses_local_path(monkeypatch, fake_dispatch):
    """无论 _should_use_local_only_connection 返回 True 还是 False，均应直写本地。"""
    monkeypatch.setattr(conn_mod, "_should_use_local_only_connection", lambda *_a, **_k: True)
    ok = dispatch_write("INSERT INTO t VALUES (?)", ("x",))
    assert ok is True
    assert fake_dispatch["local_single"] == 1
    assert fake_dispatch["queue_single"] == 0

    monkeypatch.setattr(conn_mod, "_should_use_local_only_connection", lambda *_a, **_k: False)
    ok = dispatch_write("INSERT INTO t VALUES (?)", ("y",))
    assert ok is True
    assert fake_dispatch["local_single"] == 2
    assert fake_dispatch["queue_single"] == 0
```

→ 删掉两处 `assert fake_dispatch["queue_single"] == 0` 行:
```python
def test_dispatch_write_always_uses_local_path(monkeypatch, fake_dispatch):
    """无论 _should_use_local_only_connection 返回 True 还是 False，均应直写本地。"""
    monkeypatch.setattr(conn_mod, "_should_use_local_only_connection", lambda *_a, **_k: True)
    ok = dispatch_write("INSERT INTO t VALUES (?)", ("x",))
    assert ok is True
    assert fake_dispatch["local_single"] == 1

    monkeypatch.setattr(conn_mod, "_should_use_local_only_connection", lambda *_a, **_k: False)
    ok = dispatch_write("INSERT INTO t VALUES (?)", ("y",))
    assert ok is True
    assert fake_dispatch["local_single"] == 2
```

第二个 (`test_dispatch_batch_write_always_uses_local_path`,行 70-82) 类似 — 删掉两处 `assert fake_dispatch["queue_batch"] == 0` 行。

- [ ] **Step 6: 跑测试套件**

```bash
python -m pytest tests/unit/database/test_dispatch_paths.py -v --tb=short
```

Expected: 全部用例 PASS。

- [ ] **Step 7: 提交**

```bash
git add database/execution_engine.py database/connection.py tests/unit/database/test_dispatch_paths.py
git commit -m "refactor(database): drop dead _queue_* shim functions

_queue_write_operation / _queue_batch_write_operation have been
returning False unconditionally since commit 601e7a3 (libsql backend
drop). Removed the dead functions, the corresponding re-exports in
connection.py, and the now-trivial assertions in test_dispatch_paths.

No behavioral change — these functions were already no-ops.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 重命名 `init_concurrent_system` → `init_db_session_resources`

**Files:**
- Modify: `database/execution_engine.py:76` (function definition)
- Modify: `database/connection.py:734, 740` (re-export comment + name)
- Modify: `core/study_flow.py:25, 54` (import + call site)
- Modify: `web/backend/user_context.py:197, 283, 293` (comment + import + call site)
- Modify: `web/backend/routers/users.py:102` (comment)
- Modify: `tests/web/test_users.py:61` (monkeypatch)

- [ ] **Step 1: 改函数定义 `database/execution_engine.py:76-78`**

```python
def init_concurrent_system() -> None:
    """并发系统初始化。在 pyturso 本地同步直写模式下仅输出日志。"""
    _debug_log("并发系统初始化完成（本地直写模式已就绪）", level="INFO")
```
→
```python
def init_db_session_resources() -> None:
    """DB session 资源初始化。在 pyturso 本地同步直写模式下仅输出日志（无实际并发系统启动）。"""
    _debug_log("DB session 资源就绪（本地同步直写模式）", level="INFO")
```

- [ ] **Step 2: 改 `database/connection.py:734, 740`**

第 734 行的 re-export 注释:
```python
#   - core/study_flow.py imports init_concurrent_system / cleanup_concurrent_system
```
→
```python
#   - core/study_flow.py imports init_db_session_resources / cleanup_db_session_resources
```

第 740 行的 import 名:
```python
    init_concurrent_system,
```
→
```python
    init_db_session_resources,
```

- [ ] **Step 3: 改 `core/study_flow.py`**

第 25 行 import:
```python
from database.connection import cleanup_concurrent_system, init_concurrent_system
```
→
```python
from database.connection import cleanup_db_session_resources, init_db_session_resources
```

第 54 行调用:
```python
        init_concurrent_system()
```
→
```python
        init_db_session_resources()
```

- [ ] **Step 4: 改 `web/backend/user_context.py`**

第 197 行注释:
```python
        # ⚠️ DB init (init_db + init_concurrent_system) 在后台线程跑——pyturso 首次
```
→
```python
        # ⚠️ DB init (init_db + init_db_session_resources) 在后台线程跑——pyturso 首次
```

第 283 行 import:
```python
        from database.connection import init_concurrent_system
```
→
```python
        from database.connection import init_db_session_resources
```

第 293 行调用:
```python
        init_concurrent_system()
```
→
```python
        init_db_session_resources()
```

- [ ] **Step 5: 改 `web/backend/routers/users.py:102`**

```python
            # get() 已同步执行 DB 初始化（init_db + init_concurrent_system）。
```
→
```python
            # get() 已同步执行 DB 初始化（init_db + init_db_session_resources）。
```

- [ ] **Step 6: 改 `tests/web/test_users.py:61`**

```python
        monkeypatch.setattr(db_conn, "init_concurrent_system", lambda: None)
```
→
```python
        monkeypatch.setattr(db_conn, "init_db_session_resources", lambda: None)
```

- [ ] **Step 7: 确认 0 处遗漏**

```bash
git grep "init_concurrent_system"
```

Expected: 无输出。

- [ ] **Step 8: 验证 import + 测试**

```bash
python -c "from database.connection import init_db_session_resources; print('import ok')"
python -m pytest tests/ -m "not slow" -q --tb=short -k "test_users or test_dispatch" 2>&1 | Select-Object -Last 6
```

Expected: `import ok` + 相关测试 pass。

---

## Task 4: 重命名 `cleanup_concurrent_system` → `cleanup_db_session_resources`

**Files:**
- Modify: `database/execution_engine.py:81-85` (function definition)
- Modify: `database/connection.py:741` (re-export name)
- Modify: `core/study_flow.py:25, 159` (import + call site, import 已在 Task 3 同行改好)
- Modify: `tests/conftest.py:30` (call)
- Modify: `tests/web/test_users.py:60` (monkeypatch)

- [ ] **Step 1: 改函数定义 `database/execution_engine.py:81-85`**

```python
def cleanup_concurrent_system() -> None:
    """并发系统清理，释放底层单例写连接句柄。"""
    _close_main_write_conn_singleton()
    _close_hub_write_conn_singleton()
    _debug_log("并发系统清理完成", level="INFO")
```
→
```python
def cleanup_db_session_resources() -> None:
    """DB session 资源清理：关闭主库与 Hub 的写连接 singleton 句柄。"""
    _close_main_write_conn_singleton()
    _close_hub_write_conn_singleton()
    _debug_log("DB session 资源清理完成", level="INFO")
```

- [ ] **Step 2: 改 `database/connection.py:741`**

```python
    cleanup_concurrent_system,
```
→
```python
    cleanup_db_session_resources,
```

- [ ] **Step 3: 改 `core/study_flow.py:159`**

```python
            cleanup_concurrent_system()
```
→
```python
            cleanup_db_session_resources()
```

注意:Task 3 第 3 步已经把 import 行同时更新两个名字了。如果上一步漏了 `cleanup_db_session_resources` 那条 import,这一步要补:打开 `core/study_flow.py:25`,确认 import 行已经是:
```python
from database.connection import cleanup_db_session_resources, init_db_session_resources
```

如果不是 → 现在编辑成上面这样。

- [ ] **Step 4: 改 `tests/conftest.py:30`**

```python
        db_engine.cleanup_concurrent_system()
```
→
```python
        db_engine.cleanup_db_session_resources()
```

- [ ] **Step 5: 改 `tests/web/test_users.py:60`**

```python
        monkeypatch.setattr(db_conn, "cleanup_concurrent_system", lambda: None)
```
→
```python
        monkeypatch.setattr(db_conn, "cleanup_db_session_resources", lambda: None)
```

- [ ] **Step 6: 确认 0 处遗漏**

```bash
git grep "cleanup_concurrent_system"
```

Expected: 无输出。

- [ ] **Step 7: 验证整体 import + 测试**

```bash
python -c "from database.connection import init_db_session_resources, cleanup_db_session_resources; print('imports ok')"
python -m pytest tests/ -m "not slow" -q --tb=short 2>&1 | Select-Object -Last 8
```

Expected: `imports ok` + 测试全过。

- [ ] **Step 8: 提交 (Task 3 + Task 4 合并一个 commit)**

```bash
git add database/execution_engine.py database/connection.py core/study_flow.py web/backend/user_context.py web/backend/routers/users.py tests/conftest.py tests/web/test_users.py
git commit -m "refactor(database): rename init/cleanup_concurrent_system → init/cleanup_db_session_resources

The old names implied a multi-threaded 'concurrent system' (libsql era,
when writes had to be serialized through a daemon thread). Post-pyturso
these functions only manage write singleton lifecycle — renamed to
reflect the actual responsibility.

Touches 7 files; behavior unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 刷新 docstring (write singleton 角色 + 同步标志位 + sync helpers)

**Files:**
- Modify: `database/execution_engine.py:32-50` (_db_syncing / set_db_syncing / clear_db_syncing / get_db_sync_status)
- Modify: `database/execution_engine.py:116-180` (_execute_write_sql_sync / _execute_batch_write_sql_sync)
- Modify: `database/connection.py:626-630` (_get_dedicated_write_conn)

- [ ] **Step 1: 改 `database/execution_engine.py:32-50`**

定位 `_db_syncing` 标志和 3 个 helper 函数。在文件靠近行 26-50 附近:

```python
_db_syncing = False
_db_sync_progress: Dict[str, Any] = {}  # {"started_at": float, "phase": str}

# 慢阈值（毫秒）：批写超过此值会被打成 WARNING（Phase 4.5 P95<100ms 对齐）
_SLOW_BATCH_WRITE_MS = 100

def set_db_syncing(phase: str = "") -> None:
    """标记 DB 正在同步（嵌入式副本的 conn.sync() 进行中）。"""
    global _db_syncing, _db_sync_progress
    _db_syncing = True
    _db_sync_progress = {"started_at": time.time(), "phase": phase}


def clear_db_syncing() -> None:
    """清除 DB 同步标记。"""
    global _db_syncing, _db_sync_progress
    _db_syncing = False
    _db_sync_progress = {}


def get_db_sync_status() -> Dict[str, Any]:
    """返回 DB 同步状态，供 health endpoint 使用。"""
    return {
        "syncing": _db_syncing,
        **(_db_sync_progress if _db_syncing else {}),
    }
```

只改 docstring:

`set_db_syncing` docstring 行:
```python
    """标记 DB 正在同步（嵌入式副本的 conn.sync() 进行中）。"""
```
→
```python
    """标记 DB 正在同步（pyturso push/pull 进行中）。

    由 sync_coordinator.py 在闲时同步开始/结束时调用,
    由 web/backend/app.py 的 /api/health endpoint 读取。
    """
```

`clear_db_syncing` 和 `get_db_sync_status` 的 docstring 保留(已经不含 libsql 字样),无需修改。

- [ ] **Step 2: 改 `database/execution_engine.py:116-133` (_execute_write_sql_sync docstring)**

当前函数(行 116-132):
```python
def _execute_write_sql_sync(sql: str, params: tuple = (), db_path: Optional[str] = None, conn: Any = None) -> None:
    owned = conn is None
    target_conn = conn or _get_local_conn(db_path or _config.DB_PATH)
    try:
        cur = target_conn.cursor()
        try:
            cur.execute(sql, params)
        finally:
            cur.close()
        target_conn.commit()
        _mark_main_db_needs_sync(db_path=db_path, conn=target_conn)
    finally:
        if owned:
            try:
                target_conn.close()
            except Exception:
                pass
```

在 `def` 行下、第一行代码 `owned = conn is None` 之前**插入** docstring:

```python
def _execute_write_sql_sync(sql: str, params: tuple = (), db_path: Optional[str] = None, conn: Any = None) -> None:
    """执行单条写 SQL (pyturso 同步直写)。

    pyturso 下所有写入都走这条路径:直接 conn.execute() + conn.commit(),
    没有队列、没有 batching、没有 retry。失败由调用方 (repo 层) 兜底。

    Args:
        sql:    SQL 字符串
        params: 参数 tuple
        db_path: 目标 DB 路径,None 则用 _config.DB_PATH
        conn:   可选已有连接;None 则现开 _get_local_conn 并在结束时 close
    """
    owned = conn is None
    ...
```

- [ ] **Step 3: 给 `_execute_batch_write_sql_sync` 添加类似 docstring**

定位 `def _execute_batch_write_sql_sync(...)` (约行 135),在 def 行下插入 docstring:
```python
def _execute_batch_write_sql_sync(
    sql: str,
    args_list: List[Tuple],
    db_path: Optional[str] = None,
    conn: Any = None,
) -> None:
    """执行批量写 SQL (pyturso 同步直写,批量版本)。

    单次事务跑完 args_list 里全部 row,失败整批回滚。
    超过 _SLOW_BATCH_WRITE_MS (默认 100ms) 会打 WARNING。

    Args:
        sql:       SQL 字符串(含 ? 占位符)
        args_list: 参数 tuple 列表;空列表则直接返回
        db_path:   目标 DB 路径,None 则用 _config.DB_PATH
        conn:      可选已有连接;None 则现开 _get_local_conn 并在结束时 close
    """
    if not args_list:
        return
    ...
```

- [ ] **Step 4: 改 `database/connection.py:626-630` (_get_dedicated_write_conn docstring)**

当前:
```python
def _get_dedicated_write_conn(db_path: Optional[str] = None) -> Any:
    path = db_path or _config.DB_PATH
    if _get_backend().name == "pyturso":
        return _get_local_conn(path)
    return _get_main_write_conn_singleton(do_sync=False)
```

在 `def` 行下、第一行代码之前**插入** docstring:
```python
def _get_dedicated_write_conn(db_path: Optional[str] = None) -> Any:
    """打开一个独立的写连接。

    pyturso 模式 (当前唯一支持): 永远走 _get_local_conn 现开新连接,
    不复用 write singleton。这是因为 pyturso 用 MVCC,多个并发连接到
    同一 DB 文件是安全的;libsql 时代为了避开 WAL 互斥才必须用 singleton。

    Args:
        db_path: 目标 DB 路径,None 则用 _config.DB_PATH
    """
    path = db_path or _config.DB_PATH
    ...
```

- [ ] **Step 5: 验证语法**

```bash
python -m py_compile database/execution_engine.py database/connection.py
```

Expected: no output

- [ ] **Step 6: 跑测试套件**

```bash
python -m pytest tests/ -m "not slow" -q --tb=short 2>&1 | Select-Object -Last 8
```

Expected: all pass

- [ ] **Step 7: 提交**

```bash
git add database/execution_engine.py database/connection.py
git commit -m "docs(database): refresh docstrings to reflect pyturso-native semantics

- _db_syncing / set_db_syncing: 'Embedded Replica' → 'pyturso push/pull'
- _execute_write_sql_sync / _execute_batch_write_sql_sync: add docstring
  explaining 'no queue, no batching, no retry — direct conn.execute() +
  commit()'
- _get_dedicated_write_conn: explain why pyturso always opens a new
  connection instead of reusing write singleton (MVCC, not WAL exclusion)

No behavioral changes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: 最终验证 + 推送 + 开 PR

**Files:**
- 无文件修改

- [ ] **Step 1: 跑完整测试套件**

```bash
python -m pytest tests/ -m "not slow" -q --tb=short 2>&1 | Select-Object -Last 10
```

Expected: all pass.

- [ ] **Step 2: 端到端 smoke test**

```bash
# 后台跑 backend, 验证启动 + 基本 API 不死
python scripts/start_web.py
```

观察控制台:
- 启动 banner 出来
- `/api/health` 可达 → curl 一下: `curl http://127.0.0.1:8765/api/health`,返回 200
- Ctrl+C 退出干净

(无需登录 / 实际同步,只是验证 import 链路没断、startup hook 跑通)

- [ ] **Step 3: grep 审计**

```bash
git grep "_queue_write_operation\|_queue_batch_write_operation"
git grep "init_concurrent_system\|cleanup_concurrent_system"
```

Expected: 两条命令都**零输出**。

- [ ] **Step 4: 查看 commit 历史**

```bash
git log --oneline feat/web-ui..HEAD
```

Expected: 3 个 commits — Task 2 (drop dead shims), Task 3+4 合并 (rename), Task 5 (docstring refresh)。

- [ ] **Step 5: 推送并开 PR**

```bash
git push -u origin refactor/libsql-cleanup-phase2

gh pr create --title "refactor(database): remove dead write-queue shims, consolidate write API (Phase 2)" --body "$(cat <<'EOF'
## Summary

Phase 2 of libsql residual cleanup. See [design spec](docs/superpowers/specs/2026-05-23-libsql-residual-cleanup-design.md) Phase 2 section for full context.

- 删除 `_queue_write_operation` / `_queue_batch_write_operation` 两个永远 return False 的死壳函数
- 重命名 `init_concurrent_system` → `init_db_session_resources` (反映真实职责)
- 同样重命名 `cleanup_concurrent_system` → `cleanup_db_session_resources`
- 刷新 `_execute_*_sync` / `_db_syncing` / `_get_dedicated_write_conn` 的 docstring,说明 pyturso-native 语义

**没有行为变化**。write singleton 保留(在 do_sync=True 路径仍有意义),只是把它的角色在 docstring 里讲清楚。

## Test plan

- [x] `pytest tests/` 全套通过
- [x] `python scripts/start_web.py` 启动 + `/api/health` 可达
- [x] `git grep "_queue_write_operation\|_queue_batch_write_operation"` 0 命中
- [x] `git grep "init_concurrent_system\|cleanup_concurrent_system"` 0 命中

## Depends on

Phase 1 PR (libsql-cleanup-phase1) 已 merge

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL 输出。

---

## Phase 2 完成检查清单

- [ ] 3 个 task commit 都在 `refactor/libsql-cleanup-phase2` 分支
- [ ] `pytest tests/` 全套通过
- [ ] `python scripts/start_web.py` 启动正常 (smoke test)
- [ ] `git grep "_queue_*\|init_concurrent_system\|cleanup_concurrent_system"` 全 0
- [ ] PR 已开

Phase 2 落地后, Phase 3(可选 — "Embedded Replica" 暴露面下线 + connection.py 拆分)的 plan 等你重新评估架构清晰度后再写。
