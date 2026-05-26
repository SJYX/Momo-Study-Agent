# libsql 后端技术债全面清理设计

**日期**: 2026-05-21
**范围**: 中改 — 清理死代码 + 重复代码，保留 libsql fallback 兼容路径
**策略**: pyturso 为主线优化，libsql 降级为可用 fallback，不过度设计
**扫描范围**: database/、core/、compat/、web/、scripts/、tests/ 全部 Python 文件

---

## 1. 概述

全系统扫描后识别出 4 类技术债务：

| 类别 | 条数 | 风险 |
|------|------|------|
| 整文件死代码（可直接删除） | 4 | 低 |
| 重复函数/重复代码块 | 9 | 低 |
| 死 import / 误命名 / 过时注释 | 6 | 低 |
| 重复模式（可提取辅助函数） | 3 | 低-中 |

**不做的事**（用户确认保留 libsql fallback）：
- 不删除 `backends/_libsql.py`
- 不删除 libsql 路径的 singleton 重用 / WalConflict 处理
- 不删除 `_get_cloud_conn`（libsql 可能用到）
- 不删除 `word_repo.py` 的 `fallback_columns`
- 不重构 `_apply_starvation_policy`（功能正确）
- 不做 Protocol 层大改（connection.py 的分支逻辑保留）

---

## 2. 清理清单

### 第一组：整文件删除（4 项，最大净减行）

#### 2.1 删除 `database/legacy.py`（~50 行）
- **原因**: 整个文件是 `core.db_manager` 的兼容 shim，`core.db_manager` 已不存在
- **验证**: grep 确认无任何文件 `from database.legacy import` 或 `import database.legacy`
- **内容**: 重新导出 `connection`、`hub_users`、`momo_words`、`schema`、`utils`；导入 `sqlite3` 和 `libsql` 均未使用

#### 2.2 删除 `compat/` 整个包（3 个文件，~20 行）
- **原因**: `compat/gemini_client.py` 和 `compat/maimemo_api.py` 仅做 `from core.xxx import *`
- **影响**: 3 个测试文件引用了 compat（`tests/core/test_gemini_client.py`、`tests/core/test_maimemo_api.py`、`tests/core/test_apple.py`）
- **操作**: 删除 compat/ 目录，更新 3 个测试文件的 import 路径

#### 2.3 删除 `core/log_config.py` 重复定义（~100 行）
- **原因**: 文件后半段（lines 161-259）完全复制前半段（lines 60-158），6 个函数/常量被重复定义，后者覆盖前者
- **操作**: 删除 lines 160-259 的重复定义块

---

### 第二组：connection.py 清理（7 项，~100 行净减）

#### 2.4 删除 fallback 错误分类函数（lines 62-107）
- `try/except` 块中定义的 5 个函数完全复制自 `database/utils.py`
- 注释写着 "to be fully moved into database/utils.py later"
- **操作**: 删除整个 fallback 块，将 utils 导入移到顶部常规 import 区

#### 2.5 删除未使用的模块全局变量 + setter（lines 110-116, 858-863）
- `TURSO_DB_URL = None`、`TURSO_AUTH_TOKEN = None`、`TURSO_DB_HOSTNAME = None`
- 由 `set_runtime_cloud_credentials` 设置，但 `_resolve_conn_context` 直接从 `os.getenv()` 读取
- **验证**: grep `set_runtime_cloud_credentials` 确认无调用方
- **操作**: 删除 3 个全局变量 + `set_runtime_cloud_credentials` 函数

#### 2.6 删除 `_row_to_dict`（lines 755-771）
- 与 `_repo_helpers.py` 的 `row_to_dict()` 重复
- **操作**: 删除函数，调用点改为 `from ._repo_helpers import row_to_dict`

#### 2.7 删除 `_normalize_turso_url`（lines 170-178）
- 与 `database/utils.py` 的同名函数完全相同
- 且两个版本的条件判断都是无意义的（两个分支返回相同值）
- **操作**: 删除 connection.py 版本，改为从 utils 导入

#### 2.8 删除 `_is_replica_metadata_missing_error`（lines 191-199）
- 与 `utils.py` 重复。connection.py 版本是实际被调用的
- **操作**: 删除 utils.py 中未使用的版本，保留 connection.py 版本

#### 2.9 审计并删除 re-import block（lines 865-890）
- 从 `execution_engine` 反向导入 20+ 个名称（`_write_queue`、`_writer_daemon`、`set_db_syncing` 等）
- **验证**: grep 所有调用方，确认无文件通过 `connection._write_queue` 等路径使用
- **操作**: 确认无调用方后删除整个 block

#### 2.10 更新过时的 WalConflict 注释
- lines 12-15, 570, 586-588, 777, 819 等处的注释未区分后端
- **操作**: 在注释中注明 "libsql only" 或 "pyturso: skip (MVCC)"

---

### 第三组：其他数据库模块清理（4 项，~40 行净减）

#### 2.11 删除 `database/session.py` 死 import（lines 16-19）
- `try: import libsql / except: libsql = None` — 变量从未使用
- **操作**: 删除这 4 行

#### 2.12 删除 `database/community_lookup.py` 死 import（lines 28-31）
- 同上，`libsql` 变量从未使用
- **操作**: 删除这 4 行

#### 2.13 重命名 `database/sync_service.py` 中的 `_run_libsql_sync_pipeline`
- 函数名暗示仅 libsql 使用，实际服务所有后端
- skip reason 中的 `"libsql-unavailable"` 也应改为 `"backend-unavailable"`
- **操作**: 重命名为 `_run_sync_pipeline`，更新 skip reason

#### 2.14 重命名 `database/community_lookup.py` 中的 `use_libsql_dict` 参数
- 该参数控制"手动构建 dict"，与 libsql 模块无关
- **操作**: 重命名为 `use_raw_dict`

---

### 第四组：core/ 模块清理（3 项，~30 行净减）

#### 2.15 删除 `core/mimo_client.py` 死函数 `_extract_json_array`（lines 203-217）
- 与 `core/gemini_client.py` 的同名函数重复
- 从未在 mimo_client.py 内部调用（Mimo 用 `json_repair.loads`）
- **操作**: 删除函数

#### 2.16 提取 `core/iteration_manager.py` 重复 import 模式
- `_handle_level_1_selection` 和 `_handle_level_2_refinement` 有相同的 `importlib.import_module("json_repair")` 块
- **操作**: 提取为模块级 `import json_repair` 或统一的 helper

---

### 第五组：sync_manager.py 重复模式（2 项，~30 行净减）

#### 2.17 提取 `db_path` kwarg 合并模式
- `fn(voc_id, ..., db_path=self.db_path) if self.db_path else fn(voc_id, ...)` 出现 6 次
- **操作**: 提取为 `_call_with_db_path(fn, voc_id, *, db_path, **kwargs)` 辅助函数

#### 2.18 提取 RowStatus logging 模式
- `RowStatus` 日志结构出现 5 次，格式完全相同
- **操作**: 提取为 `_log_row_status(spell, status, phase, error=None)` 辅助函数

---

### 第六组：database/utils.py 清理（1 项，~5 行净减）

#### 2.19 清理 `_normalize_turso_url` 无意义条件
- `if "." in raw or raw == "localhost": return f"libsql://{raw}" / else: return f"libsql://{raw}"`
- 两个分支完全相同，条件无意义
- **操作**: 删除条件判断，直接 `return f"libsql://{raw}"`

---

## 3. 不做的事（红线）

| 项目 | 原因 |
|------|------|
| 合并 singleton 函数 | 单独的 main/hub 变量是刻意设计 |
| 合并 `_get_local_conn` / `_get_hub_local_conn` | 语义不同，合并是过度设计 |
| 重构 `_apply_starvation_policy` | O(n) 对小队列可接受 |
| 删除 `_get_cloud_conn` | libsql fallback 可能需要 |
| 删除 `word_repo.py` fallback_columns | libsql 路径需要 |
| 删除 `sync_debouncer.py` | 保留，功能正确 |
| 重构 session.py decorators | 中改范围外 |
| 删除 libsql backend | 用户明确要求保留 fallback |
| 重构 Protocol 层 | 中改范围外，保留现有分支结构 |
| 重构 `web/backend/user_context.py` 全局 patching | 中改范围外 |
| 删除 V007 migration | 其他用户可能尚未迁移 |

---

## 4. 执行顺序

按文件分组，每组完成后跑回归测试：

| 步骤 | 文件组 | 清理项 | 预计净减行 |
|------|--------|--------|-----------|
| 1 | 删除整文件 | legacy.py, compat/, log_config.py 重复 | ~170 行 |
| 2 | connection.py | fallback 函数、全局变量、row_to_dict、normalize_url、re-import、注释 | ~100 行 |
| 3 | database/utils.py | _normalize_turso_url 无意义条件 | ~5 行 |
| 4 | session.py + community_lookup.py | 死 import | ~8 行 |
| 5 | sync_service.py + community_lookup.py | 重命名 | 0 行（纯重命名） |
| 6 | core/ | mimo_client 死函数、iteration_manager 重复 import | ~25 行 |
| 7 | sync_manager.py | 提取辅助函数 | ~30 行净减 |
| 8 | tests/ | 更新 compat/ import 路径 | 0 行 |

---

## 5. 验证策略

每个步骤完成后：
1. `python -m py_compile <改过的文件>` — 语法检查
2. `grep` 确认删除的函数无残留调用方
3. `python -m pytest tests/ -v --tb=short -m "not slow"` — 回归测试

最终全量：
- 全部回归测试通过
- connection.py 行数预计减少 80-120 行
- 整体净减行数预计 300-350 行
- 无新增 TODO/FIXME

---

## 6. 调整记录（相对初版）

初版仅覆盖 database/ 连接层。用户指出"不要偷懒，各个模块都要看到"，因此第二轮扫描扩展到：
- core/ 全部 29 个文件
- compat/ 包
- scripts/ 验证脚本
- web/ backend

**新增发现：**
- `database/legacy.py` 整文件死代码（初版未覆盖）
- `compat/` 整包死代码（初版未覆盖）
- `core/log_config.py` 整文件重复（初版未覆盖）
- `core/mimo_client.py` 死函数（初版未覆盖）
- `database/sync_service.py` 误命名（初版未覆盖）
- `core/iteration_manager.py` 重复 import（初版未覆盖）
- `_normalize_turso_url` 无意义条件（初版未覆盖）

---

## 7. ARCHITECTURE.md 架构妥协分析（"libsql Tax"）

基于对 ARCHITECTURE.md §4（并发模型）、§5（同步模型）及全部同步相关代码的深入分析：

### 7.1 结论：同步/优先级系统**大部分不是 libsql 妥协**

| 模块 | 分类 | 原因 |
|------|------|------|
| **SyncManager.PriorityQueue** | **统一必要** | 序列化墨墨 API 调用（外部限流服务），与数据库后端无关 |
| **P1/P2/P3/P4 优先级** | **统一必要** | UX 优先级（今日任务 > 手动重试 > warmup），是墨墨 API 调度不是数据库调度 |
| **防饿死策略** | **统一必要** | 防止 P1 堵塞墨墨 API 队列，与数据库无关 |
| **sync_status=2 冲突检测** | **统一必要** | 墨墨 API 级别冲突（云端释义与本地不一致），不是数据库复制冲突 |
| **db_path 参数传递** | **统一必要** | 两个后端都有独立的 DB 文件（main + hub），需要选择操作哪个 |
| **SyncDebouncer** | **统一必要** | 防止快速连续编辑触发重复 sync，网络效率优化 |
| **写入合并缓冲** | **统一妥协** | 减少 SQLite 写锁竞争，两个后端的本地文件都是 SQLite |
| **_sync_daemon 轮询结构** | **统一妥协** | 两个后端都需要后台同步，但 5s 空闲等待 + 锁获取是 libsql 约束 |
| **sync_service 超时模式** | **统一妥协** | 主要保护 libsql 持锁同步不挂死，pyturso 无此风险但有界执行仍有用 |

### 7.2 同步系统中的真实 libsql-only 妥协（仅 4 项）

| 模式 | 位置 | pyturso 需要？ |
|------|------|-------------|
| `_sync_daemon` 中的 `op_lock_for(conn)` 获取 | execution_engine.py:302 | NO — pyturso 的 op_lock_for 是 no-op yield |
| `_writer_daemon` 中的 `op_lock_for` 交互 | execution_engine.py:139 | NO — 写队列本身需要（SQLite 单写者），锁获取仅对 libsql 有意义 |
| `_run_libsql_sync_pipeline` 函数名 | sync_service.py:44 | NO — 函数是后端无关的，名字是历史遗留 |
| `"libsql-unavailable"` skip reason 字符串 | sync_service.py:154 | NO — pyturso 也走此路径，名字不准确 |

### 7.3 并发/连接层的 libsql-only 妥协

| 架构模式 | 影响范围 | 分类 |
|---------|---------|------|
| `op_lock_for` 协议 + 全部 20+ 调用点 | 10 个文件 | **统一妥协**（pyturso no-op） |
| 单写守护线程 + PriorityQueue | execution_engine.py ~150 行 | **libsql-only** |
| 连接单例 + 5 把锁变量 | connection.py ~100 行 | **libsql-only** |
| 游标铁律（`cur.close()` + `commit()`） | 全局读写路径 | **libsql-only** |
| GC hack（sync 前强制 gc.collect） | runner.py:302 | **libsql-only** |
| `should_close()` 保护（~19 调用点） | 10 个文件 | **统一妥协**（pyturso 始终 True） |
| `BEGIN IMMEDIATE` 事务 | 4 处 | **主要 libsql** |
| WalConflict 错误恢复 | execution_engine.py ~30 行 | **libsql-only** |
| 单例复用读路径 | connection.py ~40 行 | **libsql-only**（pyturso 已绕过） |

### 7.4 "libsql Tax" 量化

- **~350-400 行** connection.py + execution_engine.py 的代码主要因 libsql 约束而存在
- **~20+ 调用点**跨 10 个文件包裹 `op_lock_for` 和 `should_close` 检查，对 pyturso 是零开销的 no-op
- **架构代价**：整个写路径通过单线程 daemon 序列化，牺牲了 pyturso 原生可提供的并发能力
- **同步系统**：几乎无 libsql tax（PriorityQueue/优先级/冲突检测都是业务逻辑必需）

### 7.5 当前已做的 pyturso 优化

代码已开始分流（中改前已完成的部分）：
- **读路径分流**：pyturso 走 `_get_local_read_conn()`（独立 sqlite3），libsql 复用单例
- **写连接分流**：`_get_dedicated_write_conn()` 对 pyturso 返回本地连接，libsql 返回单例
- **同步分流**：`backend.do_sync_on()` 统一调用，pyturso 走 push/pull/checkpoint，libsql 走 conn.sync()
- **锁下沉**：`op_lock_for()` 已沉入 backend protocol，connection.py 不直接操作 threading.Lock

### 7.6 本次中改不涉及的架构优化（留待 future）

> ⚠️ 以下改动属于"大改"范围，影响面广，本次中改明确不涉及：

- **消除写队列**：pyturso 可直接并发写入，不需要 PriorityQueue + daemon 序列化
- **消除连接单例**：标准 SQLite MVCC 支持多连接并发
- **消除 `op_lock_for` 包裹**：20+ 调用点可以去掉 no-op context manager
- **消除 GC hack**：标准 SQLite 不存在僵尸游标问题
- **简化 WalConflict 错误处理**：pyturso 永远不会触发
- **简化 `_get_read_conn_impl`**：pyturso 路径已干净，libsql 路径可保留但不需要重试逻辑

这些是"如果未来完全移除 libsql 后端"后的优化方向，标记为 **FUTURE** 不在本次范围内。

---

## 8. ARCHITECTURE.md 文档更新项

清理代码的同时，需要同步更新以下文档以反映清理结果：

| 文档 | 更新内容 |
|------|---------|
| `ARCHITECTURE.md` §46 | `database/legacy.py` 行删除（已被删除） |
| `ARCHITECTURE.md` §2 表格 | 确认 legacy.py 条目移除 |
| `database/README.md` | WalConflict 注释加 "libsql only" 标注（对应 2.10） |
| `docs/dev/AI_CONTEXT.md` | 确认无 legacy.py / compat/ 引用 |
| `docs/CHANGELOG.md` | 记录本次清理 |
