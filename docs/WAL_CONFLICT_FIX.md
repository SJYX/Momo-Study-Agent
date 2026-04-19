# SQLite WAL Frame Insert Conflict 修复指南

## 问题分析

### 症状
应用在后台写入数据时频繁出现错误：
```
后台写线程批量操作出错: WAL frame insert conflict
```

### 根本原因
SQLite WAL（Write-Ahead Logging）模式下的并发锁定冲突，通常由以下场景引起：

1. **后台写线程与 libsql 同步线程争抢 WAL 锁**
   - 后台写线程执行批量写入（INSERT/UPDATE）
   - 同时 libsql embedded replica 在后台同步数据库
   - 两者竞争 WAL 文件的锁定

2. **缺少 WAL 相关的 PRAGMA 配置**
   - SQLite 默认的 `busy_timeout` 为 0（立即失败）
   - 不会自动 checkpoint WAL 文件

3. **批量写入缺少重试机制**
   - 第一次遇到锁冲突就直接抛出异常
   - 没有退避重试逻辑

## 实施的解决方案

### 1. SQLite PRAGMA 优化

#### 修改位置
在所有数据库连接初始化时添加两个 PRAGMA 配置：

**位置 A：本地连接初始化** (`_open_local_connection`)
```python
conn.execute("PRAGMA busy_timeout=5000;")      # 5秒自动重试WAL锁定冲突
conn.execute("PRAGMA wal_autocheckpoint=1000;") # 每1000页自动checkpoint
```

**位置 B：Embedded Replica 连接** (`_connect_embedded_replica`)
```python
conn.execute("PRAGMA busy_timeout=5000;")
conn.execute("PRAGMA wal_autocheckpoint=1000;")
```

**位置 C：Hub 本地连接** (`_get_hub_local_conn._open_local_connection`)
```python
conn.execute("PRAGMA busy_timeout=5000;")
conn.execute("PRAGMA wal_autocheckpoint=1000;")
```

#### 配置说明

| PRAGMA | 值 | 效果 |
|--------|-----|------|
| `busy_timeout` | 5000ms | 当遇到锁定冲突时，自动重试最多5秒（而不是立即失败）|
| `wal_autocheckpoint` | 1000页 | 每当 WAL 文件达到 1000 个页面时自动进行 checkpoint，清理 WAL 文件 |
| `synchronous` | NORMAL | 均衡性能和安全性（已存在） |

### 2. 批量写入重试逻辑

#### 修改函数：`_execute_batch_writes()`

实现三层重试机制：
- **最大重试次数**：3 次
- **退避策略**：指数退避（100ms → 200ms → 400ms）
- **错误分类**：WAL 冲突 vs 其他错误

```python
def _execute_batch_writes(write_conn: sqlite3.Connection, batch: List[Dict[str, Any]]) -> None:
    """执行批量写入操作，一次事务提交所有数据，支持WAL冲突重试。"""
    max_retries = 3
    retry_count = 0
    last_error = None
    
    while retry_count < max_retries:
        try:
            # 执行批量写入...
            write_conn.commit()
            return  # 成功后立即返回
        
        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            # 检查是否为WAL相关冲突
            is_wal_conflict = "wal" in error_msg or "database is locked" in error_msg or "frame insert conflict" in error_msg
            
            if is_wal_conflict and retry_count < max_retries - 1:
                retry_count += 1
                wait_time = 0.1 * (2 ** (retry_count - 1))  # 指数退避
                _debug_log(f"WAL冲突，等待 {wait_time*1000:.0f}ms 后重试 ({retry_count}/{max_retries})")
                time.sleep(wait_time)
                continue
            else:
                # 非WAL冲突或已达重试上限
                raise
```

#### 重试流程图
```
第1次尝试
  ↓
[失败 - WAL冲突？]
  ├─ 是 → 等待 100ms → 第2次尝试
  └─ 否 → 立即抛出异常

第2次尝试
  ↓
[失败 - WAL冲突？]
  ├─ 是 → 等待 200ms → 第3次尝试
  └─ 否 → 立即抛出异常

第3次尝试
  ↓
[失败]
  └─ 抛出异常（已达重试上限）
```

### 3. 后台写线程改进

#### 修改函数：`_writer_daemon()`

改进错误处理逻辑：
- **WAL 冲突**：保持 batch，等待 500ms 后下一轮重试
- **其他错误**：清空 batch，避免重复处理

```python
try:
    _execute_batch_writes(write_conn, pending_batch)
    # 成功处理...
    pending_batch = []

except sqlite3.OperationalError as batch_e:
    error_msg = str(batch_e).lower()
    is_wal_conflict = "wal" in error_msg or "database is locked" in error_msg
    
    if is_wal_conflict:
        # WAL 冲突：保留batch等待下一轮
        _debug_log(f"WAL冲突重试已失败，队列回补待重试")
        time.sleep(0.5)  # 给 embedded replica 更多同步时间
    else:
        # 其他错误：清空batch
        _write_queue_stats["total_errors"] += 1
        pending_batch = []
        time.sleep(0.1)
```

## 性能影响分析

### 正面影响
- ✅ **提高写入成功率**：通过自动重试，大幅减少 WAL 冲突导致的写入失败
- ✅ **减少 WAL 文件**：`wal_autocheckpoint` 定期清理 WAL，保持数据库性能
- ✅ **改善并发性**：`busy_timeout` 让线程自动等待而非立即失败，提高吞吐量
- ✅ **更好的用户体验**：AI 助记和数据同步不再中断

### 潜在开销
- ⚠️ **延迟增加**：WAL 冲突时会额外等待 100-400ms
  - 仅在高并发或 replica 同步时触发
  - 大多数情况下无感知
- ⚠️ **CPU 使用**：checkpoint 操作会消耗部分 CPU
  - 自动进行，影响可控

## 验证方法

### 日志验证
1. 运行应用进行 AI 助记生成
2. 查看日志是否仍有 `WAL frame insert conflict` 错误
3. 如果出现错误，应该看到重试日志：
   ```
   [WARNING] 批量写入WAL冲突，等待 100ms 后重试 (1/3)
   [INFO] 批量写入操作成功 (或 [ERROR] 在3次重试后仍失败)
   ```

### 性能验证
- 监控后台写线程的成功率
- 检查 `.db-wal` 和 `.db-shm` 文件大小（应保持较小）
- 观察应用响应时间（应无明显变化）

## 配置调整

如需自定义参数，可在代码中修改：

```python
# _writer_daemon() 函数
batch_threshold = 50    # 积累多少条数据后执行批量提交
timeout_seconds = 1.0   # 超时多久后强制提交

# _execute_batch_writes() 函数
max_retries = 3         # 最大重试次数
wait_time = 0.1 * (2 ** (retry_count - 1))  # 指数退避基数

# SQLite PRAGMA
PRAGMA busy_timeout=5000;         # 修改为其他值（单位：毫秒）
PRAGMA wal_autocheckpoint=1000;   # 修改为其他值（单位：页）
```

## 相关文件
- `core/db_manager.py`：主要修改文件
- `docs/CONCURRENCY_REFACTOR.md`：并发架构设计文档
- `docs/dev/AUTO_SYNC.md`：同步链路文档

## 参考资源
- [SQLite WAL Mode](https://www.sqlite.org/wal.html)
- [SQLite PRAGMA busy_timeout](https://www.sqlite.org/pragma.html#pragma_busy_timeout)
- [SQLite PRAGMA wal_autocheckpoint](https://www.sqlite.org/pragma.html#pragma_wal_autocheckpoint)
