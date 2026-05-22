# Task Plan: Drop Libsql Backend

## Goal
全面移除 libsql 后端，仅保留 pyturso 作为唯一数据库后端，并清理 pyturso 中的 libsql 遗留冗余代码（op_lock_for、should_close、_momo_db_role 等）。

## Current Phase
Phase 3

## Phases

### Phase 1: 删除 libsql 后端文件 + 简化 backends/__init__.py
- [x] 删除 `database/backends/_libsql.py`（316 行）
- [x] 删除 `.backup_pulldb/PullDB.py`
- [x] 删除 `scripts/verify_embedded_replica.py`
- [x] 删除 `scripts/verify_er_quick.py`
- [x] 删除 `scripts/_pull_monitor.py`
- [x] 修改 `database/backends/__init__.py` — 删除 HAS_LIBSQL 探针 + fallback 分支
- [x] 测试通过：490 passed
- **Status:** complete

### Phase 2: 简化 connection.py 中的 HAS_LIBSQL 条件
- [x] 删除 `HAS_LIBSQL` 导入
- [x] 15 处 `HAS_LIBSQL or HAS_PYTURSO` → `HAS_PYTURSO`
- [x] 更新错误消息 + 注释（5 处 libsql 引用）
- [x] 删除 `test_libsql_returns_singleton` 测试
- [x] 测试通过：489 passed
- **Status:** complete

### Phase 3: 清理 Protocol 接口 + 删除 pyturso 中的冗余防御
- [ ] 简化 `_protocol.py`：删 `op_lock_for`、`should_close`、`is_supported`、`is_singleton`
- [ ] 简化 `_pyturso.py`：删 `_singleton_ids`、`should_close()`、`op_lock_for()`、`is_supported()`、`_momo_db_role`、`is_singleton`、`_cleanup_stale_sidecars`
- [ ] 清理调用点：`connection.py` (~15 op_lock_for + ~12 should_close)、`session.py`、`execution_engine.py`、`community_lookup.py`、`schema.py`、`notes_repo.py`、`momo_words.py`、`sync_service.py`、`sync_coordinator.py`
- [ ] 跑测试确认无回归
- **Status:** in_progress

### Phase 4: 清理 V007 迁移 + WalConflict
- [ ] 删除 `_migrate_libsql_to_turso()` 函数
- [ ] 简化 `detect_db_format()` — 移除 `libsql_embedded_replica`
- [ ] 清理 runner.py WalConflict 测试
- [ ] 跑测试确认迁移路径正常
- **Status:** pending

### Phase 5: 清理剩余测试文件
- [ ] `test_op_lock.py` — 保留 pyturso noop 测试
- [ ] `test_protocol.py` — 清理 libsql 测试
- [ ] `test_v007_format_detection.py` — 删除 libsql sidecar 测试
- [ ] `test_robustness.py` — 修复预存 bug
- [ ] 全量测试
- **Status:** pending

### Phase 6: 清理 requirements + 脚本 + 文档
- [ ] `requirements.txt` — 删除 `libsql-experimental`
- [ ] 清理 `scripts/` 中的 libsql 引用
- [ ] 更新关键文档（README, ARCHITECTURE, AI_CONTEXT, CLAUDE.md, database/README.md）
- [ ] 最终全量测试 + py_compile
- **Status:** pending

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| 分 6 个阶段逐阶段跑测试 | 每步可回滚，避免大爆炸式变更 |
| 删 op_lock_for + should_close + is_supported | pyturso 原生 MVCC 不需要这些防御 |
| 保留 _get_main_write_conn_singleton 单例模式 | 性能价值，与 libsql 无关 |
| WalConflict 处理保留在 runner.py | 防御性检测，不会误伤 |
| V007 _migrate_libsql_to_turso 删除 | 历史迁移已完成 |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| 磁盘 I/O 错误（pyturso sync 与 writer daemon 竞争） | 1 | ProfileSyncCoordinator 加入 _wait_for_writes_drained() |
| test_db_manager_get_cloud_conn_self_healing_regression 失败 | 1 | Phase 1 中已修复 |
