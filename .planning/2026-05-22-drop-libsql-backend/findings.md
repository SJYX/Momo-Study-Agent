# Findings & Decisions — Drop Libsql Backend

## Requirements

- 全面移除 libsql 后端，仅保留 pyturso (turso.sync) 作为唯一数据库后端
- 同时清理 pyturso 中为 libsql 保留的冗余防御代码
- 保持 pyturso 路径功能完整，测试通过

## Research Findings

### 后端架构现状

`database/backends/` 包含 4 个文件：
- `_protocol.py` — `TursoBackend` Protocol 接口：`op_lock_for`, `should_close`, `connect`, `do_sync_on`, `is_supported`
- `_pyturso.py` — `PytursoBackend`，240 行，原生 MVCC 无需外部锁
- `_libsql.py` — `LibsqlBackend`，316 行，嵌入式副本 + WalConflict 防御
- `__init__.py` — `get_active_backend()` 选择逻辑：优先 pyturso → fallback libsql

### 后端选择链

```
config (env) → database/backends/__init__.py → get_active_backend()
  优先 HAS_PYTURSO (turso.sync) → PytursoBackend
  fallback HAS_LIBSQL (libsql) → LibsqlBackend
  else → raise RuntimeError
```

### HAS_LIBSQL 引用点（34 个 .py 文件）

核心引用：
- `database/connection.py` — 15 处 `if (HAS_LIBSQL or HAS_PYTURSO)` 条件
- `database/backends/__init__.py` — 探针定义 + fallback 分支
- `database/backends/_libsql.py` — 自引用

### pyturso 中的 libsql 遗留冗余

| 冗余项 | 原因 | 调用点数量 |
|--------|------|-----------|
| `op_lock_for()` 在 pyturso 是空操作 (yield) | pyturso 原生 MVCC，不需要外部锁 | ~15 |
| `_singleton_ids` / `should_close()` | pyturso 的 `_singleton_ids` 永远为空，`should_close()` 永远返回 `True` | ~12 |
| `_momo_db_role` 赋值 | pyturso 设了但没人读（只有 libsql `_resolve_lock` 读） | 1 (赋值) |
| WalConflict 处理 | pyturso MVCC 不产生 WalConflict | runner.py + 测试 |
| `_cleanup_stale_sidecars()` | pyturso 不产生 libsql sidecar | 1 (pyturso connect) |

### V007 迁移

`database/migrations/V007_migrate_db_format.py` 包含：
- `_migrate_libsql_to_turso(db_path)` — 将 libsql ER 格式的 DB 备份后删除，让 pyturso 从云端重新 bootstrap
- `detect_db_format()` — 识别 `libsql_embedded_replica` 格式
- 这些迁移在所有客户端上已执行完毕，可安全删除

### 连接单例模式

`connection.py` 中的 `_get_main_write_conn_singleton()` 保留 — pyturso 的单例模式有性能价值（避免重复连接开销），但应删掉 should_close 守卫（MVCC 下不需要判断连接是否可关闭）。

### 文件删除清单

| 文件 | 原因 |
|------|------|
| `database/backends/_libsql.py` | 整个 LibsqlBackend 类 |
| `.backup_pulldb/PullDB.py` | libsql 专用备份拉取脚本 |
| `scripts/verify_embedded_replica.py` | libsql ER 验证脚本 |
| `scripts/verify_er_quick.py` | libsql ER 快速验证脚本 |
| `scripts/_pull_monitor.py` | libsql initial pull 进度监控 |

### 测试影响（10 个文件）

| 文件 | 需删除的测试 |
|------|------------|
| `tests/unit/database/backends/test_op_lock.py` | `test_libsql_op_lock_main_and_hub_separate`, `test_libsql_op_lock_main_serialized`, `test_libsql_default_role_is_main` |
| `tests/unit/database/backends/test_protocol.py` | `test_libsql_is_supported_reflects_has_libsql`, `test_backend_preference_pyturso_over_libsql` |
| `tests/unit/database/test_read_conn_isolation.py` | `test_libsql_returns_singleton` |
| `tests/unit/database/migrations/test_v007_format_detection.py` | `test_libsql_sidecar_returns_libsql_embedded_replica` |

## Technical Decisions

| Decision | Rationale |
|----------|-----------|
| 分 6 个阶段执行，逐阶段跑测试 | 每步可回滚，避免大爆炸式变更导致难以定位回归 |
| 删 `op_lock_for` + `should_close`，保留 `connect` + `do_sync_on` | Protocol 简化；`is_supported` 在唯一后端时也无意义 → 同删 |
| WalConflict 处理保留在 runner.py | 虽然 pyturso 不产生 WalConflict，但保留作为防御性检测，仅删测试中的 libsql mock |
| V007 迁移函数 `_migrate_libsql_to_turso` 删除 | 历史迁移已完成；`pre_connect_migrate()` 保留但简化内部逻辑 |
| `connection.py` 中 `HAS_LIBSQL or HAS_PYTURSO` → `HAS_PYTURSO` | 直接等价替换，无需重写条件逻辑 |
| 保留 `_get_main_write_conn_singleton` 的单例模式 | 单例模式有性能价值（避免重复连接开销），仅删 should_close 守卫 |
| `_cleanup_stale_sidecars()` 保留在 utils.py | 虽然 libsql sidecar 消失了，但函数名泛化后可用于清理其他残留文件 |

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| 磁盘 I/O 错误：pyturso sync 与 writer daemon 竞争写锁 | 在 ProfileSyncCoordinator 中加入 `_wait_for_writes_drained()` |
