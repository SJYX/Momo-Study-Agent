# Progress Log — Drop Libsql Backend

## Session: 2026-05-22

### Phase 1: 删除 libsql 后端文件 + 简化 backends/__init__.py
- **Status:** complete
- **Started:** 2026-05-22
- Actions taken:
  - 删除 `database/backends/_libsql.py`（316 行，整个 LibsqlBackend 类）
  - 删除 `.backup_pulldb/PullDB.py`、`scripts/verify_embedded_replica.py`、`scripts/verify_er_quick.py`、`scripts/_pull_monitor.py`
  - 简化 `backends/__init__.py`：删除 HAS_LIBSQL 探针 + fallback 分支
  - `HAS_LIBSQL = False` 保留导出（connection.py 等仍导入，Phase 2 清理）
  - 预先修复 Phase 5 测试（test_op_lock.py、test_protocol.py）以解除测试阻塞
- Files deleted: 5
- Files modified: `database/backends/__init__.py`
- Test results: **490 passed**, 22 deselected, 1 xpassed

### Phase 2: 简化 connection.py 中的 HAS_LIBSQL 条件
- **Status:** complete
- Actions taken:
  - 删除 `HAS_LIBSQL` 导入（connection.py 第 36 行）
  - 15 处 `HAS_LIBSQL or HAS_PYTURSO` → `HAS_PYTURSO`
  - 更新错误消息：`"libsql 不可用"` → `"turso.sync (pyturso) 不可用"`
  - 清理 5 处注释中的 libsql 引用
  - 删除 `test_libsql_returns_singleton` 测试
- Files modified: `database/connection.py`、`tests/unit/database/test_read_conn_isolation.py`
- Test results: **489 passed**, 0 failures

### Phase 3: 清理 Protocol 接口 + 删除 pyturso 冗余防御
- **Status:** in_progress
- 待完成：简化 Protocol（删 op_lock_for/should_close/is_supported）+ 清理 ~27 个调用点

## Test Results
| Phase | Tests Passed | Notes |
|-------|-------------|-------|
| Baseline (Phase 2 commit) | 513 | 1 pre-existing failure (libsql mock bug) |
| Phase 1 | 490 | Phase 5 test fixes done early |
| Phase 2 | 489 | All green |

## Errors
| Timestamp | Error | Resolution |
|-----------|-------|------------|
| 2026-05-22 | disk I/O error (pyturso sync vs writer daemon race) | ProfileSyncCoordinator._wait_for_writes_drained() |
| 2026-05-22 | test_db_manager_get_cloud_conn_self_healing_regression | Phase 1 中已修复 |

## 5-Question Reboot Check
| Question | Answer |
|----------|--------|
| Where am I? | Phase 3 — 清理 Protocol 接口 + pyturso 冗余防御 |
| Where am I going? | Phase 4: V007/WalConflict → Phase 5: 测试 → Phase 6: 文档 |
| What's the goal? | 全面移除 libsql 后端，仅保留 pyturso |
| What have I learned? | pyturso 有大量 libsql 遗留冗余（op_lock_for ~15点, should_close ~12点, _momo_db_role） |
| What have I done? | Phase 1-2 完成，5 文件删，15 条条件简化，489 测试通过 |
