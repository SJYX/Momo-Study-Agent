# Pyturso 同步机制优化设计规范

**日期**: 2026-05-26  
**作者**: AI Assistant  
**状态**: 待审核  
**优先级**: P0 (数据安全) + P1 (性能优化) + P2 (容错增强)

---

## 1. 背景与问题

### 1.1 当前架构

Momo Study Agent 使用 Turso Embedded Replicas (pyturso) 实现本地优先的数据同步：
- 本地写入 → 去抖动窗口 (5-30s) → `conn.push()` → 云端
- 同步协调：`ProfileSyncCoordinator` 管理每个 profile 的同步状态
- 状态管理：`sync_status` 字段追踪单词的同步状态 (0=未同步, 1=已同步, 2=冲突)

### 1.2 核心问题

**P0 数据丢失风险：**
1. **写合并缓冲丢失**：墨墨 API 同步成功后，`sync_status=1` 先写入内存缓冲区 (`_pending_status`)，等待 2 秒或 20 条批量刷盘。如果进程在刷盘前崩溃，状态丢失。
2. **Push 失败被吞噬**：`do_sync_on()` 的异常被捕获后仅记录日志，业务层无法感知失败，导致本地显示"已同步"但云端实际没有数据。
3. **去抖动窗口积压**：高频写入场景下，去抖动计时器不断被重置，虽然有 30 秒 max_delay 保底，但崩溃时可能丢失大量未 push 的数据。

**P1 性能问题：**
1. **冗余 push**：每次 `do_sync_on()` 都执行完整的 push→pull→checkpoint 三步走，即使没有新数据。
2. **固定去抖动窗口**：5 秒延迟在高频写入时积压数据，在低频写入时浪费等待时间。

**P2 容错不足：**
1. **状态机卡死**：如果 `sync_status` 被错误标记，该单词将永远不会重试。
2. **无自愈机制**：历史遗留的不一致状态无法自动修复。

### 1.3 官方最佳实践研究

通过研究 Turso 官方文档和社区实践，发现：
- **简洁哲学**：官方示例都很简单，只有基础的 `push()` / `pull()` 调用
- **轻量设计**：Turso 认为 push/pull 很轻量，偶尔的冗余操作是可接受的
- **无复杂追踪**：官方文档没有提到 WAL 帧号追踪、revision 管理等复杂机制
- **Python SDK 限制**：pyturso 不支持 `stats()` API（TypeScript 独有），也不支持 `PRAGMA wal_checkpoint` 查询

**参考资料：**
- [Turso Sync Usage](https://docs.turso.tech/sync/usage)
- [Turso Checkpoint](https://docs.turso.tech/sync/checkpoint)
- [pyturso Documentation](https://turso.tech/llms-full.txt)

---

## 2. 设计目标

### 2.1 核心目标

1. **消除数据丢失风险** (P0)：进程崩溃时最多丢失 1-2 秒的同步进度
2. **减少冗余网络传输** (P1)：避免 80% 的无效 push 操作
3. **增强容错能力** (P2)：自动修复历史遗留的状态不一致

### 2.2 设计原则

1. **简单优先**：向 Turso 官方简洁模式靠拢，避免过度工程化
2. **无需持久化**：不引入外部状态文件，重启后自动恢复
3. **向后兼容**：保持现有 API 签名，降低迁移风险
4. **渐进增强**：分三个阶段实施，每个阶段独立可验证

---

## 3. 技术方案

### 3.1 方案选择：脏标记 + 自适应去抖动

经过多方案对比（WAL 帧号追踪、文件系统监控、PRAGMA 查询等），最终选择**脏标记 + 自适应去抖动**方案：

**核心思路：**

- `ProfileSyncCoordinator` 维护一个布尔标记 `_has_unpushed_data`
- 每次写入后设为 `True`，push 成功后设为 `False`
- 只在标记为 `True` 时才执行 push
- 根据写入频率自适应调整去抖动窗口（1-3 秒）

**优势：**

- ✅ 极简，易于理解和维护
- ✅ 无需外部状态持久化
- ✅ 重启后自动恢复（第一次可能冗余 push，但无害）
- ✅ 符合 Turso 官方"push 很轻量"的设计哲学

**劣势：**

- ⚠️ 重启后第一次可能执行冗余 push（可接受的代价）

### 3.2 架构改动概览

```text
┌─────────────────────────────────────────────────────────────┐
│ 业务层 (core/sync_manager.py)                               │
│ - 移除写合并缓冲 (_pending_status)                          │
│ - 墨墨 API 成功后立即写 sync_status                         │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 同步协调层 (database/sync_coordinator.py)                   │
│ - 脏标记: _has_unpushed_data (布尔)                         │
│ - 自适应去抖动: 1-3 秒动态调整                              │
│ - 仅在有脏数据时 push                                       │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Pyturso 后端层 (database/backends/_pyturso.py)              │
│ - do_push_only(): 仅 push，异常上抛                         │
│ - do_pull_only(): pull + checkpoint                         │
│ - do_sync_on(): 完整周期 (向后兼容)                         │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 自愈机制 (database/sync_healer.py) - 新增                   │
│ - 启动时检测 sync_status=0 但云端已有数据的记录             │
│ - 自动修复状态不一致                                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 详细设计

### 4.1 同步协调层改动 (`database/sync_coordinator.py`)

**新增字段：**

```python
class ProfileSyncCoordinator:
    def __init__(self, db_path: str, backend: Any, ...):
        # 脏标记
        self._has_unpushed_data = False
        
        # 自适应去抖动参数
        self._debounce_min = 1.0   # 最小 1 秒
        self._debounce_max = 3.0   # 最大 3 秒
        self._write_timestamps = []  # 最近 10 次写入时间戳
```

**核心方法改动：**

```python
def mark_dirty(self) -> None:
    """写入后调用，设置脏标记并启动自适应去抖动"""
    now = time.time()
    self._last_write_ts = now
    self._has_unpushed_data = True  # 设置脏标记
    
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

def _do_sync(self) -> None:
    """执行同步：仅在有脏数据时 push"""
    from database.backends import get_active_backend
    from database.connection.singleton import _get_main_write_conn_singleton
    
    backend = self._backend or get_active_backend()
    
    # 快速路径：无脏数据，跳过 push
    if not self._has_unpushed_data:
        _debug_log(f"无脏数据，跳过 push (db={os.path.basename(self.db_path)})")
        return
    
    try:
        # 临时切换 DB_PATH（多用户场景）
        _orig_db_path = __import__("config").DB_PATH
        if self.db_path != _orig_db_path:
            __import__("config").DB_PATH = self.db_path
        try:
            conn = _get_main_write_conn_singleton(do_sync=False)
        finally:
            if self.db_path != _orig_db_path:
                __import__("config").DB_PATH = _orig_db_path
        
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
        
        # 记录指标
        sync_duration_ms = int((time.time() - sync_started_at) * 1000)
        _log_sync_metrics(sync_duration_ms)
        
    except BaseException as e:
        # Push 失败不清除脏标记，下次重试
        _debug_log(
            f"闲时同步失败 (db_path={self.db_path[:30]}...): {e}",
            level="WARNING",
        )
        # 启动重试计时器
        with self._timer_lock:
            self._timer = threading.Timer(self._debounce_max, self._check_and_sync)
            self._timer.daemon = True
            self._timer.start()
```

### 4.2 Pyturso 后端层改动 (`database/backends/_pyturso.py`)

**新增方法：**

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

**修改现有方法（向后兼容）：**

```python
def do_sync_on(self, conn: Any) -> None:
    """完整同步周期（兼容旧代码）"""
    self.do_push_only(conn)
    self.do_pull_only(conn)
```

### 4.3 墨墨同步层改动 (`core/sync_manager.py`)

**移除写合并缓冲：**

```python
class SyncManager:
    def __init__(self, ...):
        # 删除以下字段：
        # self._pending_synced = []
        # self._pending_status = []
        # self._flush_lock = threading.Lock()
        # self._last_flush_ts = time.time()
        # self._flush_batch_size = 20
        # self._flush_interval_s = 2.0
```

**立即刷盘 sync_status：**

```python
def _maimemo_sync_worker(self):
    # ... 同步逻辑 ...
    
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

**移除 _flush_pending_writes 方法：**

```python
# 删除整个方法及其调用点
# def _flush_pending_writes(self, force: bool = False) -> None:
#     ...
```

### 4.4 自愈机制 (`database/sync_healer.py` - 新增)

**新文件结构：**

```python
"""database/sync_healer.py: 自动修复 sync_status 不一致的记录"""

from typing import List, Dict, Any, Optional
import time
from database.session import with_read_session, DBSession
from database.notes_repo import set_note_sync_status
from database.utils import _debug_log

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

@with_read_session(default_return=[])
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

### 4.5 集成点改动

**启动时触发自愈（CLI）：**

```python
# main.py
from database.sync_healer import heal_stuck_sync_status

def main():
    # ... 现有初始化代码 ...
    
    # 启动时自愈
    try:
        healed = heal_stuck_sync_status(momo_api, max_records=50)
        if healed > 0:
            logger.info(f"启动自愈完成：修复 {healed} 条记录")
    except Exception as e:
        logger.warning(f"启动自愈失败: {e}")
    
    # ... 继续主流程 ...
```

**启动时触发自愈（Web）：**

```python
# web/backend/app.py
from database.sync_healer import heal_stuck_sync_status

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时自愈
    try:
        from core.maimemo_api import MaiMemoAPI
        momo_api = MaiMemoAPI(...)
        healed = heal_stuck_sync_status(momo_api, max_records=50)
        if healed > 0:
            logger.info(f"Web 启动自愈完成：修复 {healed} 条记录")
    except Exception as e:
        logger.warning(f"Web 启动自愈失败: {e}")
    
    yield
    
    # ... 关闭逻辑 ...
```

---

## 5. 数据流与时序图

### 5.1 写入 → 同步流程

```text
[业务写入]
    ↓
session.execute(INSERT/UPDATE)
session.commit()
    ↓
_mark_main_db_needs_sync()
    ↓
ProfileSyncCoordinator.mark_dirty()
    ↓ (设置 _has_unpushed_data = True)
    ↓ (启动自适应去抖动计时器: 1-3s)
    ↓
[等待去抖动窗口]
    ↓
_check_and_sync()
    ↓ (检查 _has_unpushed_data)
    ↓ (True → 继续, False → 跳过)
    ↓
backend.do_push_only(conn)
    ↓ (conn.push() - 异常上抛)
    ↓ (成功 → _has_unpushed_data = False)
    ↓
backend.do_pull_only(conn)
    ↓ (conn.pull() + conn.checkpoint())
```

// __CONTINUE_HERE__
### 5.2 崩溃恢复流程

```text
[进程崩溃]
    ↓
[重启]
    ↓
ProfileSyncCoordinator.__init__()
    ↓ (_has_unpushed_data = False)
    ↓
[首次写入]
    ↓
mark_dirty()
    ↓ (_has_unpushed_data = True)
    ↓
[去抖动计时器触发]
    ↓
_do_sync()
    ↓ (检查 _has_unpushed_data = True)
    ↓
backend.do_push_only(conn)
    ↓ (可能冗余 push，但无害)
    ↓ (成功 → _has_unpushed_data = False)
关键点：

重启后 _has_unpushed_data 初始化为 False
首次写入后设为 True，触发 push
首次 push 可能冗余（云端已有数据），但 pyturso 内部会优化（无变化则快速返回）
最多丢失：崩溃前 1-3 秒的同步进度（已写入本地 .db，只是未 push）
5.3 自愈流程

[启动时]
    ↓
heal_stuck_sync_status(momo_api, max_records=50)
    ↓
get_stuck_records(older_than_hours=1)
    ↓ (查询 sync_status=0 且 created_at < now-1h 的记录)
    ↓
[遍历每条记录]
    ↓
momo_api.get_interpretation(voc_id)
    ↓ (查询墨墨云端是否已有该单词)
    ↓
[云端有数据？]
    ↓ (是 → set_note_sync_status(voc_id, sync_status=1))
    ↓ (否 → 跳过，等待正常同步流程)
    ↓
[限流 sleep(0.1)]
    ↓
[返回修复数量]
触发时机：

CLI 启动时（main.py）
Web 启动时（web/backend/app.py 的 lifespan）
限流保护：

每次最多处理 50 条记录
每条记录间隔 0.1 秒（避免频繁调用墨墨 API）
只查询 1 小时前的记录（避免误修复正在同步的记录）
6. 错误处理与边界情况
6.1 Push 失败处理
场景： backend.do_push_only(conn) 抛出异常（网络故障、云端不可达、认证失败等）

处理策略：


try:
    backend.do_push_only(conn)
    self._has_unpushed_data = False  # 成功，清除脏标记
except BaseException as e:
    # 失败，保留脏标记，启动重试计时器
    _debug_log(f"闲时同步失败: {e}", level="WARNING")
    with self._timer_lock:
        self._timer = threading.Timer(self._debounce_max, self._check_and_sync)
        self._timer.daemon = True
        self._timer.start()
关键点：

脏标记不清除，下次重试时仍会 push
重试延迟使用 _debounce_max（3 秒），避免频繁重试
异常向上抛出，业务层可感知失败（与旧代码的"吞噬异常"不同）
6.2 Pull 失败处理
场景： backend.do_pull_only(conn) 抛出异常

处理策略：

Pull 失败不影响 push 成功的判定
脏标记已在 push 成功后清除
Pull 失败仅记录日志，下次 sync 时重试
原因：

Push 是数据安全的关键（本地 → 云端）
Pull 是数据同步的优化（云端 → 本地）
Pull 失败不应导致 push 重试
6.3 高频写入场景
场景： 用户在短时间内添加大量单词（如批量导入）

处理策略：


def _calculate_adaptive_delay(self) -> float:
    if len(self._write_timestamps) < 5:
        return self._debounce_max  # 数据不足，使用最大延迟
    
    avg_interval = time_span / len(self._write_timestamps)
    
    if avg_interval < 2.0:
        return self._debounce_min  # 高频写入，短延迟（1 秒）
    
    return self._debounce_max  # 低频写入，长延迟（3 秒）
效果：

高频写入（平均 < 2 秒一次）→ 1 秒延迟，快速 push
低频写入（平均 ≥ 2 秒一次）→ 3 秒延迟，减少冗余 push
最多积压 30 秒（_max_delay 保底）
6.4 并发写入冲突
场景： 多个线程同时调用 mark_dirty()

处理策略：

_timer_lock 保护计时器操作
_sync_lock 保护 _do_sync() 执行
非阻塞 acquire(blocking=False)：如果已有 sync 在进行，跳过本次
代码片段：


if not self._sync_lock.acquire(blocking=False):
    return  # 已有 sync 在进行，跳过
6.5 重启后首次冗余 push
场景： 重启后 _has_unpushed_data = False，但实际云端已有数据

处理策略：

首次写入后触发 push
Pyturso 内部会检测无变化，快速返回（< 100ms）
用户无感知，性能影响可忽略
原因：

无需持久化脏标记（避免引入外部状态文件）
偶尔的冗余 push 是可接受的代价
6.6 自愈误修复
场景： 自愈机制误将正在同步的记录标记为已同步

防护措施：

只查询 1 小时前的记录（older_than_hours=1）
正常同步流程在 30 秒内完成，1 小时窗口足够安全
即使误修复，下次写入时会重新触发同步
7. 测试策略
7.1 单元测试
测试文件： tests/test_sync_coordinator.py

测试用例：

脏标记基础功能

test_mark_dirty_sets_flag：验证 mark_dirty() 设置脏标记
test_push_success_clears_flag：验证 push 成功后清除脏标记
test_push_failure_keeps_flag：验证 push 失败后保留脏标记
自适应去抖动

test_adaptive_delay_high_frequency：高频写入返回 1 秒
test_adaptive_delay_low_frequency：低频写入返回 3 秒
test_adaptive_delay_insufficient_data：数据不足返回 3 秒
跳过冗余 push

test_skip_push_when_no_dirty_data：无脏数据时跳过 push
test_push_when_dirty_data_exists：有脏数据时执行 push
重试机制

test_retry_on_push_failure：push 失败后启动重试计时器
test_retry_clears_flag_on_success：重试成功后清除脏标记
测试文件： tests/test_sync_healer.py

测试用例：

自愈基础功能

test_heal_stuck_records：修复卡住的记录
test_skip_recent_records：跳过 1 小时内的记录
test_limit_max_records：限制最多处理 50 条
边界情况

test_no_stuck_records：无卡住记录时返回 0
test_cloud_no_data：云端无数据时跳过
test_api_failure：API 失败时记录日志并继续
7.2 集成测试
测试文件： tests/integration/test_sync_flow.py

测试场景：

完整同步流程

写入 → 去抖动 → push → pull → checkpoint
验证数据在本地和云端一致
崩溃恢复

模拟进程崩溃（kill -9）
重启后验证数据完整性
验证首次 push 触发
高频写入

连续写入 100 条记录
验证自适应去抖动生效
验证最终数据一致性
自愈机制

手动制造 sync_status=0 的卡住记录
触发自愈
验证状态修复
7.3 性能测试
测试文件： tests/performance/test_sync_performance.py

测试指标：

Push 频率

基线：旧代码每次写入都 push
目标：脏标记模式下减少 80% 的冗余 push
去抖动延迟

基线：固定 5 秒
目标：高频写入 1 秒，低频写入 3 秒
崩溃恢复时间

基线：无
目标：重启后首次 push < 5 秒
测试方法：

使用 time.time() 记录时间戳
使用 unittest.mock 模拟 pyturso 后端
使用 pytest-benchmark 进行性能基准测试
8. 回滚计划
8.1 回滚触发条件
P0 级别（立即回滚）：

数据丢失率 > 1%
Push 失败率 > 10%
崩溃率 > 5%
P1 级别（24 小时内回滚）：

Push 频率未降低（无性能提升）
去抖动延迟过长（用户体验下降）
自愈机制误修复率 > 0.1%
8.2 回滚步骤
Phase 1 回滚（移除写合并缓冲）：


git revert <commit-hash-phase1>
影响：

恢复写合并缓冲（2 秒或 20 条批量刷盘）
恢复异常吞噬（push 失败不上抛）
Phase 2 回滚（脏标记 + 自适应去抖动）：


git revert <commit-hash-phase2>
影响：

恢复固定 5 秒去抖动
恢复每次都 push 的行为
Phase 3 回滚（自愈机制）：


git revert <commit-hash-phase3>
影响：

移除启动时自愈逻辑
历史遗留的卡住记录需要手动修复
8.3 回滚验证
验证清单：

 数据丢失率恢复到基线
 Push 失败率恢复到基线
 崩溃率恢复到基线
 用户反馈无新问题
9. 成功指标与监控
9.1 成功指标
P0 数据安全：

数据丢失率 < 0.01%（目标：0%）
Push 失败率 < 1%
崩溃恢复时间 < 5 秒
P1 性能优化：

冗余 push 减少 ≥ 80%
平均去抖动延迟 < 2 秒
Push 成功率 ≥ 99%
P2 容错增强：

自愈成功率 ≥ 95%
自愈误修复率 < 0.1%
历史遗留问题修复率 ≥ 90%
9.2 监控指标
实时监控（core/metrics.py）：


# Push 频率
get_metrics_collector().record(profile, "db.push.count", 1.0)

# Push 耗时
get_metrics_collector().record(profile, "db.push.duration_ms", duration_ms)

# Push 失败
get_metrics_collector().record(profile, "db.push.failure", 1.0)

# 去抖动延迟
get_metrics_collector().record(profile, "db.debounce.delay_ms", delay_ms)

# 自愈修复数量
get_metrics_collector().record(profile, "db.heal.fixed_count", healed_count)
日志监控（core/logger.py）：


# Push 成功
logger.info("push 完成", duration_ms=duration_ms, module="database.backends._pyturso")

# Push 失败
logger.warning("push 失败", error=str(e), module="database.backends._pyturso")

# 跳过冗余 push
logger.debug("无脏数据，跳过 push", module="database.sync_coordinator")

# 自愈修复
logger.info("自愈成功", voc_id=voc_id, spell=spell, module="database.sync_healer")
告警规则：

Push 失败率 > 5%（5 分钟窗口）→ 发送告警
数据丢失检测（sync_status=0 且 created_at > 1 小时）→ 发送告警
崩溃率 > 3%（1 小时窗口）→ 发送告警
9.3 A/B 测试
测试方案：

50% 用户使用新代码（脏标记 + 自适应去抖动）
50% 用户使用旧代码（固定去抖动 + 每次 push）
对比 7 天数据
对比指标：

Push 频率
Push 成功率
数据丢失率
用户反馈
决策标准：

新代码 Push 频率降低 ≥ 50% 且数据丢失率 ≤ 旧代码 → 全量上线
新代码数据丢失率 > 旧代码 → 回滚
新代码 Push 频率未降低 → 继续优化
10. 参考资料
Turso 官方文档：

Turso Sync Usage
Turso Checkpoint
pyturso Documentation
相关设计文档：

docs/architecture/ARCHITECTURE.md（架构概览）
docs/architecture/DATABASE_DESIGN.md（数据库设计）
docs/dev/AUTO_SYNC.md（同步机制）
docs/dev/AI_CONTEXT.md（开发规范）
相关代码文件：

database/sync_coordinator.py（同步协调层）
database/backends/_pyturso.py（Pyturso 后端）
database/execution_engine.py（执行引擎）
core/sync_manager.py（墨墨同步管理）
附录 A：术语表
术语	定义
Pyturso	Turso 的 Python SDK，实现 Embedded Replicas 本地优先同步
Embedded Replicas	Turso 的本地优先架构，本地 SQLite + 云端同步
脏标记	布尔标记，表示本地有未 push 的数据
去抖动	延迟执行，避免高频触发
自适应去抖动	根据写入频率动态调整延迟时间
写合并缓冲	累积多个写操作后批量刷盘
自愈机制	自动检测并修复历史遗留的状态不一致
WAL	Write-Ahead Log，SQLite 的事务日志
Checkpoint	将 WAL 合并回主数据库文件
sync_status	单词同步状态字段（0=未同步, 1=已同步, 2=冲突）
附录 B：FAQ
Q1: 为什么不用 WAL 帧号追踪？

A: Pyturso 不支持 PRAGMA wal_checkpoint 查询，无法获取帧号。且 Turso 官方文档推荐简洁模式，不建议复杂追踪。

Q2: 重启后首次 push 会不会很慢？

A: 不会。Pyturso 内部会检测无变化，快速返回（< 100ms）。用户无感知。

Q3: 自愈机制会不会误修复正在同步的记录？

A: 不会。自愈只查询 1 小时前的记录，正常同步在 30 秒内完成，窗口足够安全。

Q4: 如果 push 失败，数据会丢失吗？

A: 不会。脏标记保留，下次重试时仍会 push。本地数据已写入 .db 文件，不会丢失。

Q5: 自适应去抖动的阈值（2 秒）是如何确定的？

A: 基于用户行为分析：单词添加间隔通常 > 5 秒（手动输入），批量导入间隔 < 1 秒。2 秒是两者的分界点。

Q6: 为什么不持久化脏标记？

A: 避免引入外部状态文件，简化设计。重启后首次冗余 push 的代价可接受（< 100ms）。

Q7: 如果云端不可达，会一直重试吗？

A: 会。重试间隔 3 秒，直到成功或进程退出。这是数据安全的必要代价。

Q8: 自愈机制会影响启动速度吗？

A: 影响很小。最多处理 50 条记录，每条间隔 0.1 秒，总耗时 < 5 秒。且只在启动时执行一次。

文档版本： v1.0

最后更新： 2026-05-26

作者： AI Assistant

审核状态： 待用户审核