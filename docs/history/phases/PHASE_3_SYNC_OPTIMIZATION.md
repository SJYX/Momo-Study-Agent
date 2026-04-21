# Phase 3: 同步引擎更新（已完成）

> 状态：已完成（旧手工同步函数已移除，主/Hub 同步均使用 `conn.sync()`）

## 目标
使用 libsql Embedded Replicas 的 `conn.sync()` 方法，完全替代手工的元数据对比、时间戳对比、分块批量应用逻辑。

## 现状分析

### 当前同步逻辑（复杂）
```
1. 获取云端连接（HTTP/WS）
2. 获取本地连接（SQLite）
3. 对每个表：
   - 快速路径：对比 COUNT 和 MAX(timestamp)
   - 元数据拉取：SELECT pk, timestamp FROM table
   - 时间戳对比：找出差异键
   - 分块批量拉取：SELECT * WHERE pk IN (?) 按 50 条分块
   - 逐条写入：INSERT OR REPLACE
   - 反复提交：conn.commit() 多次
   总共 ~400 行代码，单次同步 3-10 秒
```

### 新同步逻辑（简化）
```
1. 获取 Embedded Replica 连接（libsql.connect 同时管理本地+云端）
2. 调用 conn.sync()
   - Turso 内部跟踪每个客户端的同步点位（基于 WAL 帧）
   - 每次 sync() 只传输客户端未见过的新帧
   - 本地副本自动更新，无需手工应用
   总共 ~30 行代码，单次同步 <1 秒（增量）
```

## 待消除的代码

| 函数 | 行数 | 职能 | 替代方案 |
|------|------|------|---------|
| `_sync_table()` | 93 | 元数据对比、分块批量应用 | `conn.sync()` |
| `_sync_progress_history()` | 66 | 大表增量逻辑 | `conn.sync()` |
| `_sync_hub_table()` | 102 | Hub 表同步逻辑 | `conn.sync()` (Hub 连接) |
| `sync_databases()` 内部逻辑 | ~140 | 手工同步编排 | 简化为 `conn.sync()` 调用 |
| `sync_hub_databases()` 内部逻辑 | ~150 | Hub 手工同步编排 | 简化为 `conn.sync()` 调用 |

**总计消除**: ~600 行同步代码

## 实施步骤

### Step 1: 简化 `sync_databases()`
- 删除 `_sync_table()` 和 `_sync_progress_history()` 调用
- 用 `conn.sync()` 替代所有手工同步
- 保留进度回调、错误处理、日志

### Step 2: 简化 `sync_hub_databases()`
- 删除 `_sync_hub_table()` 调用  
- 用 `conn.sync()` 替代所有手工同步
- 保留进度回调

### Step 3: 删除已消除的辅助函数
- `_sync_table()`
- `_sync_progress_history()`
- `_sync_hub_table()`

### Step 4: 验证
- 语法检查
- 导入测试
- 手工运行同步测试

## 预期效果

### 性能提升
| 场景 | 当前 | 迁移后 | 提升 |
|------|------|--------|------|
| 首次同步 | 3-10s | ~1s | **3-10x** |
| 增量同步 | 1-3s | <200ms | **5-15x** |
| 无变更检查 | ~500ms | <50ms | **10-20x** |

### 代码质量
| 指标 | 变化 |
|------|------|
| 代码行数 | -600 行 |
| 圈复杂度 | 大幅降低 |
| 可维护性 | 大幅提升 |
| 测试覆盖 | 简化后更易测试 |

## 注意事项

### 业务逻辑保留
✅ `sync_status` 标记机制保留（后台同步队列需要）  
✅ 进度回调保留（UI 需要显示同步进度）  
✅ 错误处理保留（网络异常需要报告）  
✅ 日志记录保留（诊断需要）

### 统计信息
当前可以通过 `conn.sync()` 的返回值获取统计信息：
```python
result = conn.sync()
# result 可能包含：
# - frames_synced: 已同步的帧数
# - rows_affected: 受影响的行数
# - duration_ms: 同步耗时
```

但 libsql 官方文档中 `sync()` 返回值较少，可能需要自己计算统计信息。

## 风险降低

### 兼容性
- ✅ `conn.sync()` 是 libsql 的标准方法，文档清楚
- ✅ 既有的 Embedded Replica 连接获取逻辑已验证正常
- ✅ 本地纯 SQLite 模式会跳过同步（无 sync() 方法）

### 测试
- Phase 3 修改后，同步逻辑大幅简化，实际上**更易测试**
- 可以写简单的单元测试：`conn = _get_conn(); conn.sync(); assert no errors`

## 执行结果

- `sync_databases()` 已切换为 `conn.sync()` 帧级增量同步。
- `sync_hub_databases()` 已切换为 `conn.sync()`，并通过 `_init_hub_schema()` 统一本地 Hub 表初始化。
- 已删除 `_sync_table()`、`_sync_progress_history()`、`_sync_hub_table()` 三个旧辅助函数。
- 已通过后续 Phase 4 回归测试验证（见 `PHASE_4_TESTING_VALIDATION.md`）。

## 贡献者备注

这是最后的"高收益、低风险"阶段。Phase 0-2 的连接层重构完全为 Phase 3 奠定了基础。现在只需要"删除复杂"而不涉及"引入新"。
