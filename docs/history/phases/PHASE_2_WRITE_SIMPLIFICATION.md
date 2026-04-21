# Phase 2: 写函数简化计划

## 目标
消除 Embedded Replicas 模式下不必要的双写逻辑，简化代码逻辑，提升性能。

## 背景
在旧架构中，使用手工 HTTP/WS 客户端连接 Turso，需要显式的双写：
1. 写入云端（HTTP）
2. 写入本地（SQLite）作为缓存
3. 失败回退

Embedded Replicas 模式下，这个步骤被完全自动化了：
- 一个 libsql.Connection 连接同时管理本地和云端
- 写入操作自动转发到云端，成功后自动同步本地
- 无需手工同步

## 待简化的函数

### 双写模式函数（单条写入）
| 函数名 | 当前行数 | 双写范围 | 目标 |
|--------|---------|---------|------|
| `mark_processed` | L852-875 | L860-871 | 简化为单条写入 |
| `save_ai_word_note` | L905-941 | L928-939 | 简化为单条写入 |
| `save_ai_word_iteration` | L1023-1084 | L1056-1077 | 简化为单条写入 |
| `set_note_sync_status` | L1089-1131 | L1111-1127 | 简化为单条写入 |

### 批量写入（已优化）
| 函数名 | 状态 |
|--------|------|
| `save_ai_word_notes_batch` | 已使用批量 executemany，无显式双写 |
| `log_progress_snapshots` | 基于 _get_conn()，无显式双写 |

## 简化模式

### 当前模式（双写）
```python
def mark_processed(voc_id: str, spelling: str, db_path: str = None, conn: Any = None):
    def _do_sql(cn):
        cur = cn.cursor()
        cur.execute('INSERT OR REPLACE INTO ...', args)
        if not conn: cn.commit(); cn.close()

    if conn:
        _do_sql(conn)  # 连接复用，直接写入
    else:
        path = db_path or DB_PATH
        try:
            cloud_conn = _get_conn(path)
            if _is_cloud_connection(cloud_conn):
                _do_sql(cloud_conn)  # 写入云端
                try:
                    _do_sql(_get_local_conn(path))  # 再写入本地缓存（双写！）
                except Exception as local_sync_error:
                    pass
            else:
                _do_sql(cloud_conn)  # 本地连接，直接写入
        except Exception as cloud_write_error:
            _do_sql(_get_local_conn(path))  # 失败回退本地
```

### 简化模式（单写）
```python
def mark_processed(voc_id: str, spelling: str, db_path: str = None, conn: Any = None):
    def _do_sql(cn):
        cur = cn.cursor()
        cur.execute('INSERT OR REPLACE INTO ...', args)
        if not conn: cn.commit(); cn.close()

    if conn:
        _do_sql(conn)
    else:
        path = db_path or DB_PATH
        c = _get_conn(path)  # Embedded Replica 连接（如有云端配置）
        try:
            _do_sql(c)  # 单次写入，ER 自动做本地+云端同步
        except Exception as e:
            _debug_log(f"mark_processed 写入失败: {e}")
            # 无需显式回退，Embedded Replica 的本地部分自动保证一致性
```

## 修改步骤

### Step 1: 简化 mark_processed
- 删除 if _is_cloud_connection 分支
- 删除 _get_local_conn() 显式调用
- 保留连接复用逻辑（conn 参数）

### Step 2: 简化 save_ai_word_note
- 同上

### Step 3: 简化 save_ai_word_iteration
- 同上

### Step 4: 简化 set_note_sync_status
- 同上

### Step 5: 验证与测试
- 运行全量测试
- 验证 AI 笔记的保存和同步

## 预期收益

| 指标 | 当前 | 预期变化 |
|------|------|---------|
| 代码行数 | ~120 行双写逻辑 | 减少 ~80 行 |
| 写入延迟 | 双写导致的延迟叠加 | 单次 write-through 延迟 |
| 复杂度 | 需要理解双写、回退逻辑 | 直接的 SQL+ER 自动同步 |

## 注意事项

1. **连接复用参数**: 保留 `conn` 参数，允许外部连接复用（批量操作场景）
2. **同步状态机**: 保留 `sync_status=0` 的初值，以支持后台同步队列的状态追踪
3. **错误处理**: 简化异常处理，但保留日志记录

## 贡献者备注

- 修改前：每个函数内部都需要理解"优先云端→同步本地→回退本地"的三层逻辑
- 修改后：简化为"使用 _get_conn() 获取 ER 连接，单次写入，交由 ER 自动同步"
- 这符合 AI_CONTEXT.md 中"禁止在底层函数中做同步的双写"的原则
