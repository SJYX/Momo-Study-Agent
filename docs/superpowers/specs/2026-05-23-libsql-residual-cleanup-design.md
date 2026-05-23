# libsql 残留清理与 pyturso-native 架构设计

> **日期**: 2026-05-23
> **作者**: Claude + Asher (brainstorming session)
> **状态**: design — 待 plan
> **相关**: 上游 PR `2c054e9` (background pyturso bootstrap + readiness gate);
> 历史: `601e7a3` / `8d74bb6` (drop libsql backend Phase 1-2)

## 背景

我们已经在两个 commit 里把 libsql backend 砍掉、换成 pyturso (`turso.sync`)
作为唯一后端。但是:

- 代码里**仍然散落着 libsql 时代的概念遗骸**(Embedded Replica、frame-level sync、
  WalConflict、write singleton 等),它们的实现要么已经被悄悄移除(留个空壳),
  要么按 pyturso 的语义来看名实不符。
- 注释/docstring 还在引用 libsql 术语,新读者读到会被误导。
- 没有"什么能去什么不能去"的评估文档,谁来接手都得自己重新踩一遍坑。

本设计文档把"清理"拆成 **三阶段渐进的 PR 序列**,允许在每个阶段后停步、回滚或继续。

## 目标 (Non-goals 也明确)

✅ **目标**:

- 消除"看起来还在用 libsql"的视觉噪音(注释、docstring、命名)
- 把"已经死壳化"的代码(`_queue_*` 空函数等)彻底移除
- 把"libsql 限制下做的妥协架构"评估清楚,该收敛的收敛,**让代码自述意图**
- 给后续接手者留一份决策记录,避免重蹈覆辙

❌ **明确不是目标**:

- **性能**: 不追求 pyturso MVCC 的写并发吞吐提升,不做基准测试
- **新功能**: 不引入任何业务能力变化
- **彻底重写**: 不重新设计 sync 协议、不替换 pyturso 后端
- **风险消除**: 不引入 feature flag、不做长生命周期的兼容桥接层(这反而违背"清晰度"目标)

## 整体方案 — Approach A (直接切)

三个串行 PR,每个 PR 一条独立分支:

| Phase | PR Title | 风险 | 净行数 | 必做 |
|---|---|---|---|---|
| 1 | `chore(database): refresh libsql residual comments + drop dead compat shims` | 低 | ~150 改注释 / ~30 删 | ✅ |
| 2 | `refactor(database): remove dead write-queue shims, consolidate write API` | 中 | ~80 删 / 6-8 处改名 | ✅ |
| 3 | `refactor: drop 'Embedded Replica' surface + split connection.py` | 中 | ~400 行搬家 / ~10 处改名 | ⏸ 可选 |

**分支策略**:

- 每个 Phase 一条特性分支(`refactor/libsql-cleanup-phase{N}`)从 `feat/web-ui` 切出
- 每条分支独立 PR,合并回 `feat/web-ui`
- **没有 long-lived 集成分支**,**不引入 feature flag** (与"清晰度"目标冲突)
- 三个 PR 严格按 1→2→3 顺序(因为 Phase 2 改的部分依赖 Phase 1 已合并的状态)

**Phase 3 是可选的**: 落地 Phase 2 后重新评估。如果当时觉得架构已经足够清晰,Phase 3
可以无限期推迟或永久跳过,不损失功能价值。

## Phase 1: 注释刷新 + 死代码兜底删除

**PR title**: `chore(database): refresh libsql residual comments + drop dead compat shims`

### 范围 — 注释 / docstring 刷新(13 个文件,纯文档,行为不变)

| 文件 | 行 | 改动内容 |
|---|---|---|
| `database/community_lookup.py` | 175 | "兼容 libsql ER 和 pyturso 两种格式" → "兼容 pyturso 格式" |
| `database/notes_repo.py` | 195, 240 | `# libsql/queue 抛出` → `# pyturso/queue 抛出` |
| `database/_repo_helpers.py` | 14, 27 | docstring `libsql/sqlite3` → `pyturso/sqlite3` |
| `database/momo_words.py` | 9 | 模块 docstring 中 sync_service.py 描述按 pyturso 术语重写 |
| `database/sync_service.py` | 3, 168, 210, 211 | 模块 docstring "Embedded Replica 帧级同步管线" → "pyturso push/pull 同步管线"; 3 处用户可见的 message key 改述 |
| `database/utils.py` | 77, 478, 480, 483, 485, 503, 561 | `_normalize_turso_url` docstring + `_cleanup_stale_sidecars` 7 处注释 |
| `database/migrations/__init__.py` | 2, 11 | "SQLite/libsql user_version" → "pyturso user_version"; "Replica 策略"段重写 |
| `database/migrations/V007_migrate_db_format.py` | 10, 173, 195 | 3 处保留对 "libsql ER format" 的历史描述(V007 就是用来清理 libsql 遗留文件的), 加注 "(legacy)" 表明仅为历史兼容 |
| `database/migrations/V001_initial.py` | 57 | `libsql 以 sequence/dict 返回` → `pyturso 以 sequence/dict 返回` |
| `database/migrations/runner.py` | 6, 12, 13, 50, 93, 200, 204, 278 | 8 处 "libsql sync" 全替换为 "pyturso sync" |
| `database/connection.py` | 10, 13, 560 | 顶部 docstring 删除 "Embedded Replica connection rules"/"WalConflict rule"(已不适用); 行 559 `_get_cloud_conn` **整个函数删除**(见下面死代码删除节) |
| `database/execution_engine.py` | 25 | "DB 级别的 Embedded Replica 同步状态" → "DB 级别的同步状态" |
| `web/backend/user_context.py` | 291 | 删掉"pyturso 不需要 libsql 的'重建连接' workaround"这条已无意义的安抚性注释 |

### 范围 — 死代码 / 兼容垫片删除

| 项目 | 操作 | 理由 |
|---|---|---|
| `database/backends/__init__.py:10-11` (`HAS_LIBSQL = False`) | **删除** | 全工程 0 处 import |
| `database/backends/__init__.py:7` 附近注释 | 改为 "libsql backend permanently removed in commit 8d74bb6" | 防止后人误以为还能加回来 |
| `database/connection.py:559+` (`_get_cloud_conn`) | **删除整个函数** (~30 行) | 仅被 1 个集成测试调用, 产线 0 调用 |
| `tests/integration/database/test_robustness.py` 中 `test_db_manager_get_cloud_conn_self_healing_regression` | **删除整个测试函数** | 测试的 "libsql self-healing" 在 pyturso 下语义不存在 |
| `tests/integration/database/test_robustness.py:5` 的 `from database.connection import _get_cloud_conn` | **删除 import** | 跟着上面 |

### Phase 1 验证

- `pytest tests/` 全套通过 (应该全过, 因为只动注释 + 删未被调用的代码)
- `git grep -i "libsql\|embedded replica" -- '*.py'` 期望剩余命中仅在:
  - `database/migrations/V007_migrate_db_format.py` (历史描述, 带 "(legacy)" 标注)
  - `scripts/archived/` (归档脚本, 不动)
  - 测试中无害的字符串字面量(如 `"libsql://fake.turso.io"` URL 示例)

### Phase 1 明确不动

- 前端任何文件
- 后端 API endpoint / schema 命名
- 任何函数签名 / 行为
- write singleton 相关代码

## Phase 2: 移除死壳队列 + 收敛写 API

**PR title**: `refactor(database): remove dead write-queue shims, consolidate write API`

### 背景发现

在 brainstorming 阶段查码发现: `_queue_write_operation` /
`_queue_batch_write_operation` 已经是 **永远 return False 的空函数**, 上游
`601e7a3` 那次 commit 已经把队列调度的真实逻辑移除了, 只剩空壳函数还顶着名字
"compatibility"。所以 Phase 2 的工作量比最初设想的"完全移除队列基础设施"小得多 ——
这些"基础设施"在功能层早已不存在, 我们只是删掉残留的命名和空壳。

### 范围 — 死代码删除(~80 行)

| 项目 | 位置 | 操作 |
|---|---|---|
| `_queue_write_operation()` 函数体 | `execution_engine.py:66-68` | 删除 |
| `_queue_batch_write_operation()` 函数体 | `execution_engine.py:71-73` | 删除 |
| 上述两个函数的 mock patch | `tests/unit/database/test_dispatch_paths.py:48-51` | 删除对应 monkeypatch (该测试可能整个不再有意义, 一并评估) |
| `connection.py:736-739` re-export 列表 | `connection.py` 末尾 | 去掉 `_queue_write_operation`, `_queue_batch_write_operation` 两个名字 (保留 `_execute_write_sql_sync`, `_execute_batch_write_sql_sync` 因为仍是公共 API) |

### 范围 — 函数重命名 (反映现状)

| 当前名 | 新名 | 调用点 |
|---|---|---|
| `init_concurrent_system()` | `init_db_session_resources()` | `web/backend/user_context.py`, `core/study_flow.py`, 若干 test |
| `cleanup_concurrent_system()` | `cleanup_db_session_resources()` | 同上 (cleanup 入口) |

预估 6-8 处调用点需要同步更新。

### 范围 — docstring 刷新 (说明真实意图)

| 函数 | 新 docstring 要点 |
|---|---|
| `_execute_write_sql_sync` | "pyturso 同步直写, 直接 `conn.execute()` + `conn.commit()`, 无队列" |
| `_execute_batch_write_sql_sync` | 同上, 批量版本 |
| `_db_syncing` / `set_db_syncing` / `get_db_sync_status` | 删去 "Embedded Replica" 字样, 改为 "DB 同步进行中标志位 (sync_coordinator 写, ops endpoint 读)" |
| `_get_dedicated_write_conn` | 重写: "pyturso 下永远走新连接 (`_get_local_conn`), 不复用 singleton (libsql 时代 singleton 是为了 WAL 互斥, pyturso MVCC 不需要)" |
| `init_db_session_resources` / `cleanup_db_session_resources` | "连接生命周期管理 (主库 + Hub 单例 close)" |

### 范围 — write singleton 评估结论

**保留** `_main_write_conn_singleton` / `_hub_write_conn_singleton`:

- 仅用于 `do_sync=True` 路径 (`init_db()` 一次性 + `do_sync_on()` 显式触发)
- 其他写入路径 (`_get_local_conn`, `_get_dedicated_write_conn`) **已经绕过 singleton** ——
  每次开新连接
- singleton 在这条窄路径上的存在是合理的: 避免每次显式 sync 都重建一个 80~141s
  bootstrap 的连接

Phase 2 不动 singleton 本身, 只是把它的角色在 docstring 里讲清楚。

### Phase 2 不动的部分

- 业务调用方 (`notes_repo.py`/`progress_repo.py`/`momo_words.py` 等) **不改 API**,
  继续调 `_execute_write_sql_sync` 或 `_execute_batch_write_sql_sync`
- **不引入** `with_write_session` 装饰器 (现有 `_execute_*_sync` 就是直写, 已经
  足够 "pyturso-native", 装饰器是过度设计)
- `sync_coordinator.py` / `sync_priority.py` 不动 (这俩与"写队列"无关, 处理的是
  云端 push/pull 调度)
- write singleton 不删

### Phase 2 验证

- `pytest tests/` 全套通过
- 端到端 `python scripts/start_web.py` 浏览器手动跑一遍业务流程 (登录、看 Today、
  执行同步)
- `git grep "_queue_write_operation\|_queue_batch_write_operation"` 0 命中
- `git grep "init_concurrent_system\|cleanup_concurrent_system"` 0 命中

### Phase 2 不做的事 (Stop conditions)

- 不引入 feature flag 切换新旧路径
- 不写并发 stress test (没引入新并发模型)
- 不重构调用方代码风格 (保持业务模块手感不变)

## Phase 3 (可选): "Embedded Replica" 暴露面下线 + connection.py 拆分

**PR title** (若执行): `refactor: drop 'Embedded Replica' surface + split connection.py`

### 启动门槛

Phase 2 落地后**重新评估**:

- 当前架构是否足够清晰?
- `connection.py` 700 行是否成为开发障碍?
- UI 上 "replica" 字样是否还出现在用户视线?

回答全是 "否" → Phase 3 跳过。回答有一个 "是" → Phase 3 启动。

### 范围 — 后端 API + schema 改名

| Current | Renamed to | Files |
|---|---|---|
| `/api/ops/db/replica-health` 端点 | `/api/ops/db/sync-health` | `web/backend/routers/ops.py` |
| `EmbeddedReplicaHealth` schema | `SyncHealthSnapshot` | `web/backend/schemas.py:413+` |
| 注释 "Embedded Replica 健康快照" | "Pyturso 同步健康快照" | 同上 |

### 范围 — 前端 UI 改名

| Current | Renamed to | Files |
|---|---|---|
| `DbReplicaCard.tsx` | `DbSyncCard.tsx` | `web/frontend/src/components/ops/` |
| 组件内文案 "嵌入式副本健康" | "云端同步健康" | 同上 |
| `replicaHealth` TS 类型 | `syncHealth` | `web/frontend/src/api/types.ts` 等 |

### 范围 — 拆分 `database/connection.py` (700+ 行)

新结构 (路径 `database/connection/`, 包形态):

```text
database/connection/
├── __init__.py        # re-export 全部公共名, 保持外部 import 不破
├── factory.py         # 连接工厂: _get_local_conn / _get_local_read_conn / _get_conn
├── singleton.py       # 写单例: _main_write_conn_singleton, _hub_write_conn_singleton
└── context.py         # 上下文解析: _resolve_conn_context, _is_main_db_path, helpers
```

**外部 import 兼容性约束**: `from database.connection import _get_local_conn` 等
原有写法必须仍然能工作。`__init__.py` 通过 re-export 实现透明搬家。

### Phase 3 验证

- `pytest tests/` 通过
- `npm run build` 通过 (前端 TS 类型一致)
- 前端 ops 监控页手动点一遍, 确认看不到 "嵌入式副本" / "Embedded Replica" 字样
- `git grep -i "embedded replica" -- '*.py' '*.tsx'` 0 命中
- `git grep "from database.connection import"` 命中数和 Phase 2 后一致 (没有把别人
  的 import 写法弄坏)

## 跨阶段总验证

| 维度 | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| 单元测试 | 全过 | 全过 | 全过 |
| 集成测试 | 全过 (test_robustness 少一个用例) | 全过 | 全过 |
| 前端构建 | 不涉及 | 不涉及 | `npm run build` 过 |
| 端到端 | 不需要 | start_web 跑一遍 | start_web + ops 页面手动测 |
| Grep 验证 | libsql 字样剩余只在 V007/archived | `_queue_*` / `init_concurrent_system` 0 命中 | "Embedded Replica" 0 命中 |
| 回滚成本 | revert PR (零代价) | revert PR | revert PR + 前端重新 build |

## 失败回滚

每个 Phase 都是独立 PR。任何 Phase 上线后发现回归:

1. `git revert <PR-merge-commit>` (单次 revert 即可恢复到该 Phase 前状态)
2. 不需要数据库迁移回滚 (本设计完全不涉及 DB schema 变化)
3. 不需要前端配置回滚 (Phase 1/2 不涉及前端; Phase 3 是改名, 即使部分上线、前端旧
   名也能容忍)

## 不需要解决的"伪问题" (避免争论)

为了防止下游 plan/implementation 阶段引入不必要复杂度, 这里明确以下**不做**:

| 不做 | 原因 |
|---|---|
| 引入 `WRITE_QUEUE_ENABLED` 之类 feature flag | 与"清晰度"目标直接冲突 |
| 引入 `with_write_session` 装饰器层 | 现有 `_execute_*_sync` 就是直写, 装饰器是过度设计 |
| 替换 / 撤销 write singleton | 仍然在 `do_sync=True` 窄路径有意义, 不破不立 |
| 改写业务模块调用方式 | API 不变, 不引入无谓 churn |
| 性能基准 / 并发 stress test | 不追求性能目标, 没必要 |
| 单独建立 `compat/` 目录放垫片 | 没有需要保留向后兼容的外部消费者 |

## 落地文档(Phase 完成后更新)

每个 Phase 合并时, 在对应 commit 里更新:

- `docs/dev/DECISIONS.md` 追加 DEC-### 描述本 Phase 的决策
- `docs/api/turso_api.md §14` 若涉及新踩坑则追加
- `CLAUDE.md` "模块地图"部分若有命名变化则同步

## 相关历史 commit

- `601e7a3` refactor: drop libsql backend — Phase 1-2 (pyturso only)
- `8d74bb6` refactor(database): drop libsql backend and fix cloud pull routing
- `2c054e9` feat(web): background pyturso bootstrap + readiness gate
- 本设计 `docs/superpowers/specs/2026-05-23-libsql-residual-cleanup-design.md`
