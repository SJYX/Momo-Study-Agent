# Pyturso 同步机制优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 优化 pyturso 同步机制，消除数据丢失风险，减少冗余 push，增强容错能力

**Architecture:** 三阶段实施 - Phase 1 修复 P0 数据丢失（移除写合并缓冲、异常上抛），Phase 2 优化性能（脏标记、自适应去抖动、拆分 push/pull），Phase 3 增强容错（自愈机制）

**Tech Stack:** Python 3.12+, pyturso, SQLite, threading, pytest

---

## 文件结构概览

**Phase 1 - P0 数据安全修复：**
- Modify: `core/sync_manager.py` - 移除写合并缓冲，立即刷盘 sync_status
- Modify: `database/backends/_pyturso.py` - 拆分 push/pull 方法，异常上抛
- Create: `tests/test_sync_manager_immediate_flush.py` - 验证立即刷盘行为

**Phase 2 - P1 性能优化：**
- Modify: `database/sync_coordinator.py` - 添加脏标记、自适应去抖动
- Modify: `database/backends/_pyturso.py` - 使用新拆分的 push/pull 方法
- Create: `tests/test_sync_coordinator_dirty_flag.py` - 验证脏标记逻辑
- Create: `tests/test_sync_coordinator_adaptive_debounce.py` - 验证自适应去抖动

**Phase 3 - P2 容错增强：**
- Create: `database/sync_healer.py` - 自愈机制
- Modify: `main.py` - 启动时触发自愈（CLI）
- Modify: `web/backend/app.py` - 启动时触发自愈（Web）
- Create: `tests/test_sync_healer.py` - 验证自愈机制

---

## Phase 1: P0 数据安全修复

### Task 1: 拆分 pyturso push/pull 方法

**Files:**
- Modify: `database/backends/_pyturso.py:198-231`
- Test: `tests/test_pyturso_backend_split_methods.py`

- [ ] **Step 1: 编写测试 - do_push_only 基础功能**

创建测试文件 `tests/test_pyturso_backend_split_methods.py`:

```python
"""测试 pyturso 后端拆分的 push/pull 方法"""
import pytest
from unittest.mock import Mock, patch
from database.backends._pyturso import PytursoBackend


def test_do_push_only_calls_conn_push():
    """验证 do_push_only 调用 conn.push()"""
    backend = PytursoBackend()
    mock_conn = Mock()
    mock_conn.push = Mock()
    
    backend.do_push_only(mock_conn)
    
    mock_conn.push.assert_called_once()


def test_do_push_only_propagates_exception():
    """验证 do_push_only 向上抛出异常"""
    backend = PytursoBackend()
    mock_conn = Mock()
    mock_conn.push = Mock(side_effect=RuntimeError("Network error"))
    
    with pytest.raises(RuntimeError, match="Network error"):
        backend.do_push_only(mock_conn)


def test_do_push_only_skips_if_no_push_method():
    """验证 do_push_only 在连接无 push 方法时跳过"""
    backend = PytursoBackend()
    mock_conn = Mock(spec=[])  # 无 push 方法
    
    # 不应抛出异常
    backend.do_push_only(mock_conn)
```

- [ ] **Step 2: 运行测试验证失败**

运行: `pytest tests/test_pyturso_backend_split_methods.py -v`
预期: FAIL - `AttributeError: 'PytursoBackend' object has no attribute 'do_push_only'`

- [ ] **Step 3: 实现 do_push_only 方法**

在 `database/backends/_pyturso.py` 的 `PytursoBackend` 类中添加方法（在 `do_sync_on` 方法之前）:

```python
def do_push_only(self, conn: Any) -> None:
    """仅推送本地更改到云端（异常向上抛出）"""
    if not hasattr(conn, 'push'):
        return
    
    _t_push = time.time()
    conn.push()  # 异常不捕获，向上抛出
    _debug_log(
        f"[pyturso] push 完成",
        start_time=_t_push,
        level="INFO",
        module="database.backends._pyturso",
    )
```

- [ ] **Step 4: 运行测试验证通过**

运行: `pytest tests/test_pyturso_backend_split_methods.py::test_do_push_only_calls_conn_push -v`
预期: PASS

- [ ] **Step 5: 编写测试 - do_pull_only 基础功能**

在 `tests/test_pyturso_backend_split_methods.py` 中添加:

```python
def test_do_pull_only_calls_conn_pull_and_checkpoint():
    """验证 do_pull_only 调用 conn.pull() 和 conn.checkpoint()"""
    backend = PytursoBackend()
    mock_conn = Mock()
    mock_conn.pull = Mock(return_value=True)
    mock_conn.checkpoint = Mock()
    
    backend.do_pull_only(mock_conn)
    
    mock_conn.pull.assert_called_once()
    mock_conn.checkpoint.assert_called_once()


def test_do_pull_only_skips_if_no_pull_method():
    """验证 do_pull_only 在连接无 pull 方法时跳过"""
    backend = PytursoBackend()
    mock_conn = Mock(spec=[])  # 无 pull 方法
    
    # 不应抛出异常
    backend.do_pull_only(mock_conn)
```

- [ ] **Step 6: 运行测试验证失败**

运行: `pytest tests/test_pyturso_backend_split_methods.py::test_do_pull_only_calls_conn_pull_and_checkpoint -v`
预期: FAIL - `AttributeError: 'PytursoBackend' object has no attribute 'do_pull_only'`

- [ ] **Step 7: 实现 do_pull_only 方法**

在 `database/backends/_pyturso.py` 的 `do_push_only` 方法之后添加:

```python
def do_pull_only(self, conn: Any) -> None:
    """仅拉取云端更改 + checkpoint"""
    if not hasattr(conn, 'pull'):
        return
    
    _t_pull = time.time()
    changed = conn.pull()  # 返回是否有变化
    _debug_log(
        f"[pyturso] pull 完成 (changed={changed})",
        start_time=_t_pull,
        level="INFO",
        module="database.backends._pyturso",
    )
    
    _t_ckpt = time.time()
    conn.checkpoint()
    _debug_log(
        f"[pyturso] checkpoint 完成",
        start_time=_t_ckpt,
        level="INFO",
        module="database.backends._pyturso",
    )
```

- [ ] **Step 8: 运行测试验证通过**

运行: `pytest tests/test_pyturso_backend_split_methods.py::test_do_pull_only_calls_conn_pull_and_checkpoint -v`
预期: PASS

- [ ] **Step 9: 修改 do_sync_on 使用新方法**

在 `tests/test_pyturso_backend_split_methods.py` 中添加测试:

```python
def test_do_sync_on_calls_push_and_pull():
    """验证 do_sync_on 调用 do_push_only 和 do_pull_only"""
    backend = PytursoBackend()
    mock_conn = Mock()
    mock_conn.push = Mock()
    mock_conn.pull = Mock(return_value=False)
    mock_conn.checkpoint = Mock()
    
    backend.do_sync_on(mock_conn)
    
    mock_conn.push.assert_called_once()
    mock_conn.pull.assert_called_once()
    mock_conn.checkpoint.assert_called_once()
```

- [ ] **Step 10: 运行测试验证当前行为**

运行: `pytest tests/test_pyturso_backend_split_methods.py::test_do_sync_on_calls_push_and_pull -v`
预期: PASS（当前实现已经调用 push/pull/checkpoint）

- [ ] **Step 11: 重构 do_sync_on 使用新方法**

修改 `database/backends/_pyturso.py` 中的 `do_sync_on` 方法:

```python
def do_sync_on(self, conn: Any) -> None:
    """完整同步周期（兼容旧代码）"""
    self.do_push_only(conn)
    self.do_pull_only(conn)
```

- [ ] **Step 12: 运行所有测试验证重构成功**

运行: `pytest tests/test_pyturso_backend_split_methods.py -v`
预期: 所有测试 PASS

- [ ] **Step 13: 提交 Phase 1 Task 1**

```bash
git add database/backends/_pyturso.py tests/test_pyturso_backend_split_methods.py
git commit -m "refactor(database): split pyturso push/pull into separate methods

- Add do_push_only() method that propagates exceptions
- Add do_pull_only() method for pull + checkpoint
- Refactor do_sync_on() to use new methods
- Add comprehensive unit tests

Ref: docs/superpowers/specs/2026-05-26-pyturso-sync-optimization-design.md Phase 1"
```

---

### Task 2: 移除 sync_manager 写合并缓冲

**Files:**
- Modify: `core/sync_manager.py:__init__`, `core/sync_manager.py:_maimemo_sync_worker`
- Test: `tests/test_sync_manager_immediate_flush.py`

- [ ] **Step 1: 编写测试 - 验证立即刷盘行为**

创建测试文件 `tests/test_sync_manager_immediate_flush.py`:

```python
"""测试 SyncManager 立即刷盘行为"""
import pytest
from unittest.mock import Mock, patch, call
from core.sync_manager import SyncManager


@patch('core.sync_manager.set_note_sync_status')
@patch('core.sync_manager.mark_note_synced')
def test_sync_success_immediately_writes_status(mock_mark_synced, mock_set_status):
    """验证墨墨同步成功后立即写入 sync_status"""
    manager = SyncManager(db_path="test.db", logger=Mock())
    
    # 模拟墨墨 API 返回成功
    with patch.object(manager, '_momo_api') as mock_api:
        mock_api.sync_interpretation.return_value = {
            "status": "success",
            "cloud_interpretation": "test content"
        }
        
        # 触发同步（需要根据实际实现调整）
        manager._process_sync_item({
            "voc_id": "123",
            "spell": "test",
            "interpretation": "test content"
        })
    
    # 验证立即调用了写入方法
    mock_set_status.assert_called_once()
    mock_mark_synced.assert_called_once()


def test_no_pending_buffer_fields():
    """验证 SyncManager 不再有写合并缓冲字段"""
    manager = SyncManager(db_path="test.db", logger=Mock())
    
    # 验证缓冲字段已移除
    assert not hasattr(manager, '_pending_synced')
    assert not hasattr(manager, '_pending_status')
    assert not hasattr(manager, '_flush_lock')
    assert not hasattr(manager, '_last_flush_ts')
```

- [ ] **Step 2: 运行测试验证当前行为**

运行: `pytest tests/test_sync_manager_immediate_flush.py -v`
预期: FAIL - 测试会失败，因为当前代码仍有缓冲字段

- [ ] **Step 3: 读取 sync_manager.py 找到缓冲相关代码**

运行: `grep -n "_pending_status\|_pending_synced\|_flush" core/sync_manager.py`

记录需要删除的行号和方法。

- [ ] **Step 4: 移除 __init__ 中的缓冲字段**

在 `core/sync_manager.py` 的 `__init__` 方法中删除以下字段:

```python
# 删除这些行：
# self._pending_synced = []
# self._pending_status = []
# self._flush_lock = threading.Lock()
# self._last_flush_ts = time.time()
# self._flush_batch_size = 20
# self._flush_interval_s = 2.0
```

- [ ] **Step 5: 修改 _maimemo_sync_worker 立即刷盘**

在 `core/sync_manager.py` 的 `_maimemo_sync_worker` 方法中，找到同步成功的代码块，修改为立即写入:

```python
if sync_status == 1:
    synced_content = clean_for_maimemo(
        sync_result.get("cloud_interpretation", "") if isinstance(sync_result, dict) else interpretation
    ) or synced_content
    
    # 立即写入数据库，不经过缓冲区
    set_note_sync_status(
        voc_id,
        sync_status=1,
        match_confidence=match_confidence,
        match_reason=match_reason,
        last_synced_content=synced_content,
        db_path=self.db_path
    )
    mark_note_synced(voc_id, spell, db_path=self.db_path)
    
    self.logger.info(f"✅ {spell} 墨墨同步完成并立即刷盘")
    self._log_row_status(spell, "done", "sync_done", "同步完成")
```

移除原有的缓冲逻辑（`self._pending_status.append(...)` 等）。

- [ ] **Step 6: 删除 _flush_pending_writes 方法**

在 `core/sync_manager.py` 中删除整个 `_flush_pending_writes` 方法及其所有调用点。

搜索并删除所有 `self._flush_pending_writes()` 调用。

- [ ] **Step 7: 运行测试验证修改**

运行: `pytest tests/test_sync_manager_immediate_flush.py -v`
预期: PASS

- [ ] **Step 8: 运行现有 sync_manager 测试确保无回归**

运行: `pytest tests/ -k sync_manager -v`
预期: 所有测试 PASS

- [ ] **Step 9: 提交 Phase 1 Task 2**

```bash
git add core/sync_manager.py tests/test_sync_manager_immediate_flush.py
git commit -m "fix(sync): remove write merge buffer, flush sync_status immediately

- Remove _pending_status and _pending_synced buffers
- Write sync_status to database immediately after momo API success
- Delete _flush_pending_writes method and all call sites
- Eliminates 2s/20-record window where data could be lost on crash

Fixes: P0 data loss risk from buffered writes
Ref: docs/superpowers/specs/2026-05-26-pyturso-sync-optimization-design.md"
```

---

## Phase 2: P1 性能优化

### Task 3: 添加脏标记到 ProfileSyncCoordinator

**Files:**
- Modify: `database/sync_coordinator.py:__init__`, `database/sync_coordinator.py:mark_dirty`, `database/sync_coordinator.py:_do_sync`
- Test: `tests/test_sync_coordinator_dirty_flag.py`

- [ ] **Step 1: 编写测试 - 脏标记基础功能**

创建测试文件 `tests/test_sync_coordinator_dirty_flag.py`:

```python
"""测试 ProfileSyncCoordinator 脏标记功能"""
import pytest
import time
from unittest.mock import Mock, patch
from database.sync_coordinator import ProfileSyncCoordinator


def test_mark_dirty_sets_flag():
    """验证 mark_dirty() 设置脏标记"""
    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=Mock(),
        debounce_seconds=1.0
    )
    
    assert coordinator._has_unpushed_data is False
    
    coordinator.mark_dirty()
    
    assert coordinator._has_unpushed_data is True


def test_push_success_clears_flag():
    """验证 push 成功后清除脏标记"""
    mock_backend = Mock()
    mock_backend.do_push_only = Mock()
    mock_backend.do_pull_only = Mock()
    
    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=mock_backend,
        debounce_seconds=0.1
    )
    
    coordinator._has_unpushed_data = True
    
    with patch('database.sync_coordinator._get_main_write_conn_singleton') as mock_conn:
        coordinator._do_sync()
    
    assert coordinator._has_unpushed_data is False


def test_push_failure_keeps_flag():
    """验证 push 失败后保留脏标记"""
    mock_backend = Mock()
    mock_backend.do_push_only = Mock(side_effect=RuntimeError("Network error"))
    
    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=mock_backend,
        debounce_seconds=0.1
    )
    
    coordinator._has_unpushed_data = True
    
    with patch('database.sync_coordinator._get_main_write_conn_singleton'):
        coordinator._do_sync()
    
    # 失败后脏标记应保留
    assert coordinator._has_unpushed_data is True
```

- [ ] **Step 2: 运行测试验证失败**

运行: `pytest tests/test_sync_coordinator_dirty_flag.py::test_mark_dirty_sets_flag -v`
预期: FAIL - `AttributeError: 'ProfileSyncCoordinator' object has no attribute '_has_unpushed_data'`

- [ ] **Step 3: 在 __init__ 中添加脏标记字段**

在 `database/sync_coordinator.py` 的 `ProfileSyncCoordinator.__init__` 方法中添加:

```python
def __init__(
    self,
    db_path: str,
    backend: Any,
    debounce_seconds: float = 5.0,
    max_delay_seconds: float = 30.0,
):
    self.db_path = db_path
    self._backend = backend
    self._debounce = debounce_seconds
    self._max_delay = max_delay_seconds

    self._last_write_ts = 0.0
    self._first_dirty_ts: Optional[float] = None
    self._timer: Optional[threading.Timer] = None
    self._timer_lock = threading.Lock()
    self._sync_lock = threading.Lock()
    
    # 新增：脏标记
    self._has_unpushed_data = False
```

- [ ] **Step 4: 修改 mark_dirty 设置脏标记**

在 `database/sync_coordinator.py` 的 `mark_dirty` 方法开头添加:

```python
def mark_dirty(self) -> None:
    """Called after a successful write. Starts/resets the debounce timer."""
    now = time.time()
    self._last_write_ts = now
    self._has_unpushed_data = True  # 设置脏标记
    
    # ... 其余现有代码保持不变 ...
```

- [ ] **Step 5: 修改 _do_sync 检查脏标记**

在 `database/sync_coordinator.py` 的 `_do_sync` 方法开头添加快速路径:

```python
def _do_sync(self) -> None:
    """Execute push → pull → checkpoint."""
    from database.backends import get_active_backend
    from database.connection.singleton import _get_main_write_conn_singleton
    from database.utils import _debug_log
    
    backend = self._backend or get_active_backend()
    base = os.path.basename(self.db_path)
    
    # 快速路径：无脏数据，跳过 push
    if not self._has_unpushed_data:
        _debug_log(f"无脏数据，跳过 push (db={base})")
        return
    
    # ... 其余现有代码保持不变 ...
```

- [ ] **Step 6: 修改 _do_sync 在 push 成功后清除脏标记**

在 `database/sync_coordinator.py` 的 `_do_sync` 方法中，将原有的 `backend.do_sync_on(conn)` 替换为:

```python
sync_started_at = time.time()

# 仅 push（新方法）
from database.execution_engine import set_db_syncing, clear_db_syncing
set_db_syncing(phase="idle_push")
try:
    backend.do_push_only(conn)
    self._has_unpushed_data = False  # Push 成功，清除脏标记
finally:
    clear_db_syncing()

# Pull + checkpoint（新方法）
set_db_syncing(phase="idle_pull")
try:
    backend.do_pull_only(conn)
finally:
    clear_db_syncing()
```

- [ ] **Step 7: 修改 _do_sync 异常处理保留脏标记**

在 `database/sync_coordinator.py` 的 `_do_sync` 方法的 `except` 块中，确保失败时不清除脏标记:

```python
except BaseException as e:
    # Push 失败不清除脏标记，下次重试
    _debug_log(
        f"闲时后台自动同步失败 (db_path={self.db_path[:30]}...): {e}",
        level="WARNING",
        module="database.sync_coordinator",
    )
    # 启动重试计时器
    with self._timer_lock:
        self._timer = threading.Timer(self._debounce, self._check_and_sync)
        self._timer.daemon = True
        self._timer.start()
```

- [ ] **Step 8: 运行测试验证脏标记功能**

运行: `pytest tests/test_sync_coordinator_dirty_flag.py -v`
预期: 所有测试 PASS

- [ ] **Step 9: 提交 Phase 2 Task 3**

```bash
git add database/sync_coordinator.py tests/test_sync_coordinator_dirty_flag.py
git commit -m "feat(sync): add dirty flag to skip redundant push operations

- Add _has_unpushed_data boolean flag to ProfileSyncCoordinator
- Set flag on mark_dirty(), clear on successful push
- Skip push when flag is False (no unpushed data)
- Preserve flag on push failure for retry
- Split do_sync_on into do_push_only + do_pull_only calls

Reduces redundant push operations by ~80%
Ref: docs/superpowers/specs/2026-05-26-pyturso-sync-optimization-design.md Phase 2"
```

---

### Task 4: 添加自适应去抖动

**Files:**
- Modify: `database/sync_coordinator.py:__init__`, `database/sync_coordinator.py:mark_dirty`
- Create: `database/sync_coordinator.py:_calculate_adaptive_delay`
- Test: `tests/test_sync_coordinator_adaptive_debounce.py`

- [ ] **Step 1: 编写测试 - 自适应去抖动逻辑**

创建测试文件 `tests/test_sync_coordinator_adaptive_debounce.py`:

```python
"""测试 ProfileSyncCoordinator 自适应去抖动功能"""
import pytest
import time
from unittest.mock import Mock
from database.sync_coordinator import ProfileSyncCoordinator


def test_adaptive_delay_high_frequency():
    """验证高频写入返回最小延迟（1 秒）"""
    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=Mock(),
        debounce_seconds=5.0
    )
    
    # 模拟高频写入：10 次写入在 2 秒内
    now = time.time()
    coordinator._write_timestamps = [
        now - 2.0, now - 1.8, now - 1.6, now - 1.4, now - 1.2,
        now - 1.0, now - 0.8, now - 0.6, now - 0.4, now - 0.2
    ]
    
    delay = coordinator._calculate_adaptive_delay()
    
    assert delay == 1.0  # 最小延迟


def test_adaptive_delay_low_frequency():
    """验证低频写入返回最大延迟（3 秒）"""
    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=Mock(),
        debounce_seconds=5.0
    )
    
    # 模拟低频写入：5 次写入在 20 秒内
    now = time.time()
    coordinator._write_timestamps = [
        now - 20.0, now - 15.0, now - 10.0, now - 5.0, now - 1.0
    ]
    
    delay = coordinator._calculate_adaptive_delay()
    
    assert delay == 3.0  # 最大延迟


def test_adaptive_delay_insufficient_data():
    """验证数据不足时返回最大延迟"""
    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=Mock(),
        debounce_seconds=5.0
    )
    
    # 只有 3 次写入（< 5）
    now = time.time()
    coordinator._write_timestamps = [now - 2.0, now - 1.0, now - 0.5]
    
    delay = coordinator._calculate_adaptive_delay()
    
    assert delay == 3.0  # 数据不足，使用最大延迟
```

- [ ] **Step 2: 运行测试验证失败**

运行: `pytest tests/test_sync_coordinator_adaptive_debounce.py::test_adaptive_delay_high_frequency -v`
预期: FAIL - `AttributeError: 'ProfileSyncCoordinator' object has no attribute '_calculate_adaptive_delay'`

- [ ] **Step 3: 在 __init__ 中添加自适应去抖动字段**

在 `database/sync_coordinator.py` 的 `ProfileSyncCoordinator.__init__` 方法中添加:

```python
# 新增：自适应去抖动参数
self._debounce_min = 1.0   # 最小 1 秒
self._debounce_max = 3.0   # 最大 3 秒
self._write_timestamps = []  # 最近 10 次写入时间戳
```

- [ ] **Step 4: 实现 _calculate_adaptive_delay 方法**

在 `database/sync_coordinator.py` 的 `ProfileSyncCoordinator` 类中添加新方法（在 `mark_dirty` 之前）:

```python
def _calculate_adaptive_delay(self) -> float:
    """根据写入频率自适应调整去抖动窗口"""
    if len(self._write_timestamps) < 5:
        return self._debounce_max  # 数据不足，使用最大延迟
    
    # 计算平均写入间隔
    now = time.time()
    time_span = now - self._write_timestamps[0]
    avg_interval = time_span / len(self._write_timestamps)
    
    # 高频写入（平均 < 2 秒一次）→ 短延迟
    if avg_interval < 2.0:
        return self._debounce_min
    
    return self._debounce_max
```

- [ ] **Step 5: 修改 mark_dirty 使用自适应延迟**

在 `database/sync_coordinator.py` 的 `mark_dirty` 方法中，添加时间戳记录并使用自适应延迟:

```python
def mark_dirty(self) -> None:
    """Called after a successful write. Starts/resets the debounce timer."""
    now = time.time()
    self._last_write_ts = now
    self._has_unpushed_data = True
    
    # 记录写入时间戳用于自适应计算
    self._write_timestamps.append(now)
    if len(self._write_timestamps) > 10:
        self._write_timestamps.pop(0)
    
    # 计算自适应延迟
    delay = self._calculate_adaptive_delay()
    
    with self._timer_lock:
        if self._first_dirty_ts is None:
            self._first_dirty_ts = now
        max_remaining = max(0.0, (self._first_dirty_ts + self._max_delay) - now)
        delay = min(delay, max_remaining)
        
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(delay, self._check_and_sync)
        self._timer.daemon = True
        self._timer.start()
```

- [ ] **Step 6: 运行测试验证自适应去抖动**

运行: `pytest tests/test_sync_coordinator_adaptive_debounce.py -v`
预期: 所有测试 PASS

- [ ] **Step 7: 提交 Phase 2 Task 4**

```bash
git add database/sync_coordinator.py tests/test_sync_coordinator_adaptive_debounce.py
git commit -m "feat(sync): add adaptive debounce based on write frequency

- Add _calculate_adaptive_delay() method
- Track last 10 write timestamps
- High frequency (avg < 2s): 1s delay
- Low frequency (avg >= 2s): 3s delay
- Insufficient data (< 5 samples): 3s delay

Reduces latency for batch imports while avoiding excessive push for single edits
Ref: docs/superpowers/specs/2026-05-26-pyturso-sync-optimization-design.md Phase 2"
```

---

## Phase 3: P2 容错增强

### Task 5: 实现自愈机制

**Files:**
- Create: `database/sync_healer.py`
- Test: `tests/test_sync_healer.py`

- [ ] **Step 1: 编写测试 - 自愈基础功能**

创建测试文件 `tests/test_sync_healer.py`:

```python
"""测试自愈机制"""
import pytest
from unittest.mock import Mock, patch
from database.sync_healer import get_stuck_records, heal_stuck_sync_status


@patch('database.sync_healer.with_read_session')
def test_get_stuck_records_returns_old_unsynced(mock_decorator):
    """验证 get_stuck_records 返回超过 1 小时未同步的记录"""
    mock_session = Mock()
    mock_session.fetchall.return_value = [
        ("123", "test", "2026-05-26 10:00:00"),
        ("456", "word", "2026-05-26 09:00:00")
    ]
    
    # 直接调用函数（绕过装饰器）
    from database.sync_healer import get_stuck_records
    records = get_stuck_records.__wrapped__(
        older_than_hours=1,
        limit=50,
        db_path=None,
        session=mock_session
    )
    
    assert len(records) == 2
    assert records[0]["voc_id"] == "123"
    assert records[0]["spell"] == "test"


@patch('database.sync_healer.set_note_sync_status')
@patch('database.sync_healer.get_stuck_records')
def test_heal_stuck_sync_status_fixes_records(mock_get_stuck, mock_set_status):
    """验证 heal_stuck_sync_status 修复卡住的记录"""
    mock_get_stuck.return_value = [
        {"voc_id": "123", "spell": "test", "created_at": "2026-05-26 10:00:00"}
    ]
    
    mock_api = Mock()
    mock_api.get_interpretation.return_value = {"content": "test interpretation"}
    
    healed = heal_stuck_sync_status.__wrapped__(
        mock_api,
        max_records=50,
        db_path=None,
        session=Mock()
    )
    
    assert healed == 1
    mock_set_status.assert_called_once_with("123", sync_status=1, db_path=None)


@patch('database.sync_healer.get_stuck_records')
def test_heal_stuck_sync_status_skips_if_no_cloud_data(mock_get_stuck):
    """验证云端无数据时跳过修复"""
    mock_get_stuck.return_value = [
        {"voc_id": "123", "spell": "test", "created_at": "2026-05-26 10:00:00"}
    ]
    
    mock_api = Mock()
    mock_api.get_interpretation.return_value = None  # 云端无数据
    
    healed = heal_stuck_sync_status.__wrapped__(
        mock_api,
        max_records=50,
        db_path=None,
        session=Mock()
    )
    
    assert healed == 0
```

- [ ] **Step 2: 运行测试验证失败**

运行: `pytest tests/test_sync_healer.py -v`
预期: FAIL - `ModuleNotFoundError: No module named 'database.sync_healer'`

- [ ] **Step 3: 创建 sync_healer.py 文件头部**

创建文件 `database/sync_healer.py`:

```python
"""database/sync_healer.py: 自动修复 sync_status 不一致的记录"""

from typing import List, Dict, Any, Optional
import time
from database.session import with_read_session, DBSession
from database.notes_repo import set_note_sync_status
from database.utils import _debug_log
```

- [ ] **Step 4: 实现 get_stuck_records 函数**

在 `database/sync_healer.py` 中添加:

```python
def get_stuck_records(
    older_than_hours: int = 1,
    limit: int = 50,
    db_path: Optional[str] = None,
    session: DBSession = None
) -> List[Dict[str, Any]]:
    """查询超过指定小时数仍未同步的记录"""
    sql = """
        SELECT voc_id, spell, created_at
        FROM ai_word_notes
        WHERE sync_status = 0
        AND datetime(created_at) < datetime('now', '-' || ? || ' hours')
        ORDER BY created_at DESC
        LIMIT ?
    """
    rows = session.fetchall(sql, (older_than_hours, limit))
    return [
        {
            "voc_id": str(row[0]),
            "spell": str(row[1]),
            "created_at": str(row[2])
        }
        for row in rows
    ]
```

- [ ] **Step 5: 实现 heal_stuck_sync_status 函数**

在 `database/sync_healer.py` 中添加:

```python
@with_read_session(default_return=0)
def heal_stuck_sync_status(
    momo_api,
    max_records: int = 50,
    db_path: Optional[str] = None,
    session: DBSession = None
) -> int:
    """修复卡在 sync_status=0 但云端已有数据的记录
    
    Returns:
        修复的记录数量
    """
    stuck_records = get_stuck_records(
        older_than_hours=1,
        limit=max_records,
        db_path=db_path,
        session=session
    )
    
    if not stuck_records:
        return 0
    
    healed_count = 0
    for record in stuck_records:
        voc_id = record['voc_id']
        spell = record['spell']
        
        try:
            # 查询墨墨云端是否已有该单词
            cloud_note = momo_api.get_interpretation(voc_id)
            if cloud_note:
                # 云端有数据，修复状态
                set_note_sync_status(voc_id, sync_status=1, db_path=db_path)
                healed_count += 1
                _debug_log(
                    f"自愈成功: {spell} (voc_id={voc_id}) 云端已有数据，修复 sync_status",
                    level="INFO",
                    module="database.sync_healer"
                )
        except Exception as e:
            _debug_log(
                f"自愈失败: {spell} (voc_id={voc_id}) - {e}",
                level="WARNING",
                module="database.sync_healer"
            )
        
        # 限流：避免频繁调用墨墨 API
        time.sleep(0.1)
    
    return healed_count
```

- [ ] **Step 6: 运行测试验证实现**

运行: `pytest tests/test_sync_healer.py -v`
预期: 所有测试 PASS

- [ ] **Step 7: 提交 Phase 3 Task 5**

```bash
git add database/sync_healer.py tests/test_sync_healer.py
git commit -m "feat(sync): add self-healing mechanism for stuck sync_status

- Add get_stuck_records() to query records stuck at sync_status=0
- Add heal_stuck_sync_status() to check cloud and fix status
- Query records older than 1 hour (avoids false positives)
- Rate limit: 0.1s between API calls, max 50 records per run
- Comprehensive unit tests

Ref: docs/superpowers/specs/2026-05-26-pyturso-sync-optimization-design.md Phase 3"
```

---

### Task 6: 集成自愈到启动流程

**Files:**
- Modify: `main.py`
- Modify: `web/backend/app.py`
- Test: Manual verification

- [ ] **Step 1: 在 main.py 中添加自愈调用**

在 `main.py` 的 `main()` 函数中，找到初始化完成后的位置（在创建 `momo_api` 之后），添加:

```python
# 启动时自愈
try:
    from database.sync_healer import heal_stuck_sync_status
    healed = heal_stuck_sync_status(momo_api, max_records=50)
    if healed > 0:
        logger.info(f"启动自愈完成：修复 {healed} 条记录")
except Exception as e:
    logger.warning(f"启动自愈失败: {e}")
```

- [ ] **Step 2: 在 web/backend/app.py 中添加自愈调用**

在 `web/backend/app.py` 的 `lifespan` 函数中，找到启动逻辑部分，添加:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... 现有启动代码 ...
    
    # 启动时自愈
    try:
        from database.sync_healer import heal_stuck_sync_status
        from core.maimemo_api import MaiMemoAPI
        
        # 获取或创建 momo_api 实例（根据实际代码调整）
        momo_api = MaiMemoAPI(...)
        healed = heal_stuck_sync_status(momo_api, max_records=50)
        if healed > 0:
            logger.info(f"Web 启动自愈完成：修复 {healed} 条记录")
    except Exception as e:
        logger.warning(f"Web 启动自愈失败: {e}")
    
    yield
    
    # ... 关闭逻辑 ...
```

- [ ] **Step 3: 手动验证 CLI 启动自愈**

运行: `python main.py`

检查日志中是否有自愈相关输出。如果有卡住的记录，应该看到修复日志。

- [ ] **Step 4: 手动验证 Web 启动自愈**

运行: `python -m web.backend --user test`

检查日志中是否有自愈相关输出。

- [ ] **Step 5: 提交 Phase 3 Task 6**

```bash
git add main.py web/backend/app.py
git commit -m "feat(sync): integrate self-healing into startup flow

- Add heal_stuck_sync_status() call to main.py CLI startup
- Add heal_stuck_sync_status() call to web/backend/app.py lifespan
- Non-blocking: failures logged as warnings, don't block startup
- Runs once per startup, processes up to 50 stuck records

Ref: docs/superpowers/specs/2026-05-26-pyturso-sync-optimization-design.md Phase 3"
```

---

## 验证与文档

### Task 7: 集成测试

**Files:**
- Create: `tests/integration/test_sync_optimization_flow.py`

- [ ] **Step 1: 编写集成测试 - 完整同步流程**

创建测试文件 `tests/integration/test_sync_optimization_flow.py`:

```python
"""集成测试：完整同步优化流程"""
import pytest
import time
from unittest.mock import Mock, patch
from database.sync_coordinator import ProfileSyncCoordinator
from database.backends._pyturso import PytursoBackend


@pytest.mark.integration
def test_write_triggers_adaptive_sync():
    """验证写入触发自适应同步流程"""
    mock_backend = Mock(spec=PytursoBackend)
    mock_backend.do_push_only = Mock()
    mock_backend.do_pull_only = Mock()
    
    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=mock_backend,
        debounce_seconds=0.1,
        max_delay_seconds=1.0
    )
    
    # 模拟高频写入
    for i in range(5):
        coordinator.mark_dirty()
        time.sleep(0.05)
    
    # 等待去抖动触发
    time.sleep(0.2)
    
    # 验证 push 被调用
    assert mock_backend.do_push_only.call_count >= 1
    assert mock_backend.do_pull_only.call_count >= 1
```

- [ ] **Step 2: 编写集成测试 - 脏标记跳过冗余 push**

在 `tests/integration/test_sync_optimization_flow.py` 中添加:

```python
@pytest.mark.integration
def test_dirty_flag_skips_redundant_push():
    """验证脏标记跳过冗余 push"""
    mock_backend = Mock(spec=PytursoBackend)
    mock_backend.do_push_only = Mock()
    mock_backend.do_pull_only = Mock()
    
    coordinator = ProfileSyncCoordinator(
        db_path="test.db",
        backend=mock_backend,
        debounce_seconds=0.1
    )
    
    # 第一次写入并同步
    coordinator.mark_dirty()
    time.sleep(0.2)
    
    initial_push_count = mock_backend.do_push_only.call_count
    
    # 触发第二次同步（无新写入）
    with patch('database.sync_coordinator._get_main_write_conn_singleton'):
        coordinator._do_sync()
    
    # 验证没有额外的 push
    assert mock_backend.do_push_only.call_count == initial_push_count
```

- [ ] **Step 3: 运行集成测试**

运行: `pytest tests/integration/test_sync_optimization_flow.py -v`
预期: 所有测试 PASS

- [ ] **Step 4: 提交集成测试**

```bash
git add tests/integration/test_sync_optimization_flow.py
git commit -m "test(sync): add integration tests for sync optimization

- Test write triggers adaptive sync flow
- Test dirty flag skips redundant push
- Verify end-to-end behavior

Ref: docs/superpowers/specs/2026-05-26-pyturso-sync-optimization-design.md"
```

---

### Task 8: 更新文档

**Files:**
- Modify: `docs/dev/AUTO_SYNC.md`
- Modify: `docs/architecture/DATABASE_DESIGN.md`

- [ ] **Step 1: 更新 AUTO_SYNC.md 文档**

在 `docs/dev/AUTO_SYNC.md` 中添加新的同步机制说明:

```markdown
## 同步优化（2026-05-26）

### 脏标记机制

`ProfileSyncCoordinator` 维护 `_has_unpushed_data` 布尔标记：
- 写入后设为 `True`
- Push 成功后设为 `False`
- 仅在标记为 `True` 时执行 push

**效果：** 减少 80% 的冗余 push 操作

### 自适应去抖动

根据写入频率动态调整去抖动窗口：
- 高频写入（平均 < 2 秒）→ 1 秒延迟
- 低频写入（平均 ≥ 2 秒）→ 3 秒延迟
- 数据不足（< 5 样本）→ 3 秒延迟

**效果：** 批量导入时降低延迟，单次编辑时减少冗余 push

### 自愈机制

启动时自动检测并修复卡住的记录：
- 查询 `sync_status=0` 且超过 1 小时的记录
- 检查墨墨云端是否已有数据
- 云端有数据则修复状态为 `sync_status=1`
- 限流：每条记录间隔 0.1 秒，最多 50 条

**触发时机：** CLI 和 Web 启动时
```

- [ ] **Step 2: 更新 DATABASE_DESIGN.md 文档**

在 `docs/architecture/DATABASE_DESIGN.md` 的同步状态机部分添加:

```markdown
## 同步状态机优化（2026-05-26）

### 立即刷盘

墨墨 API 同步成功后，`sync_status` 立即写入数据库，不再经过写合并缓冲。

**原因：** 消除进程崩溃时 2 秒或 20 条记录的数据丢失窗口

### 异常上抛

`do_push_only()` 方法不再捕获异常，向上抛出给调用方处理。

**原因：** 业务层可感知 push 失败，避免本地显示"已同步"但云端无数据的问题
```

- [ ] **Step 3: 提交文档更新**

```bash
git add docs/dev/AUTO_SYNC.md docs/architecture/DATABASE_DESIGN.md
git commit -m "docs(sync): document sync optimization changes

- Add dirty flag mechanism explanation
- Add adaptive debounce documentation
- Add self-healing mechanism description
- Update sync state machine with immediate flush and exception propagation

Ref: docs/superpowers/specs/2026-05-26-pyturso-sync-optimization-design.md"
```

---

## 最终验证

### Task 9: 端到端验证

**Manual verification steps:**

- [ ] **Step 1: 验证 P0 数据安全**

1. 启动程序，添加 5 个单词
2. 在墨墨同步完成后立即 kill -9 进程
3. 重启程序，检查数据库中 `sync_status` 是否正确
4. 预期：所有同步成功的单词 `sync_status=1`

- [ ] **Step 2: 验证 P1 性能优化**

1. 启动程序，开启 DEBUG 日志
2. 添加 1 个单词，观察日志中的 push 次数
3. 等待 5 秒，观察是否有冗余 push
4. 预期：只有 1 次 push，无冗余操作

- [ ] **Step 3: 验证自适应去抖动**

1. 批量导入 10 个单词（间隔 < 1 秒）
2. 观察日志中的去抖动延迟
3. 预期：延迟约 1 秒（高频模式）

- [ ] **Step 4: 验证 P2 自愈机制**

1. 手动将数据库中某个单词的 `sync_status` 改为 0
2. 将 `created_at` 改为 2 小时前
3. 重启程序
4. 检查日志中是否有自愈成功的记录
5. 预期：该单词的 `sync_status` 被修复为 1

- [ ] **Step 5: 运行完整测试套件**

运行: `pytest tests/ -v --tb=short`
预期: 所有测试 PASS

- [ ] **Step 6: 最终提交**

```bash
git add -A
git commit -m "feat(sync): complete pyturso sync optimization

Summary of changes:
- P0: Remove write merge buffer, immediate flush, exception propagation
- P1: Add dirty flag, adaptive debounce (1-3s), split push/pull
- P2: Add self-healing mechanism for stuck records

Performance improvements:
- Reduce redundant push by ~80%
- Adaptive debounce: 1s for batch, 3s for single edits
- Crash recovery: max 1-3s data loss window (down from 2-30s)

Testing:
- 15+ unit tests covering all new functionality
- Integration tests for end-to-end flow
- Manual verification of all three phases

Ref: docs/superpowers/specs/2026-05-26-pyturso-sync-optimization-design.md
Ref: docs/superpowers/plans/2026-05-26-pyturso-sync-optimization.md"
```

---

## 执行说明

**Plan complete and saved to `docs/superpowers/plans/2026-05-26-pyturso-sync-optimization.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
