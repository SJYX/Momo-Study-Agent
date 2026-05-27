# Phase 3: 'Embedded Replica' 暴露面下线 + connection.py 拆分 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把后端 API `/api/ops/db/replica-health` 改名为 `/api/ops/db/sync-health`,schema `DbReplicaHealthResponse` 改名为 `DbSyncHealthResponse`;前端组件 `DbReplicaCard.tsx` 改名为 `DbSyncCard.tsx`,所有"DB 副本健康"文案改为"DB 同步健康";把 725 行的单文件 `database/connection.py` 拆分为 `database/connection/` 包(`context.py` / `factory.py` / `singleton.py` / `__init__.py`),外部 import 通过 `__init__.py` re-export 保持兼容,唯一例外是 `web/backend/routers/ops.py` 直接 import 写单例可变全局的位置改为从子模块拿(避免 Python `from … import` 把可变全局变成快照)。

**Architecture:** 3 个独立 commit,从 Phase 2 合并后的 `feat/web-ui` 切出 `refactor/libsql-cleanup-phase3` 分支:

- C1 = 后端 rename (endpoint + schema)
- C2 = 前端 rename (TS type + 组件文件 + UI 文案)
- C3 = 拆分 `connection.py` 单文件 → `connection/` 包 + ops.py 单例 import 适配

**Tech Stack:** Python 3.12+, React + TypeScript + Vite, pytest, npm。无新依赖。

**Reference:** [`docs/superpowers/specs/2026-05-23-libsql-residual-cleanup-design.md`](../specs/2026-05-23-libsql-residual-cleanup-design.md) Phase 3 section.

**Prerequisite:** Phase 1 + Phase 2 PR 均已 merge 回 `feat/web-ui` (commit `655cccc` 已在 main 之前)。

---

## Task 1: 分支准备

**Files:**
- 无文件修改, 仅 git 操作

- [ ] **Step 1: 切回 feat/web-ui 拉最新 (确保已包含 Phase 1 + Phase 2)**

```bash
git checkout feat/web-ui
git pull --ff-only
```

Expected: fast-forward 或 already up-to-date,日志里能看到 `655cccc Merge branch 'refactor/libsql-cleanup-phase2' into feat/web-ui` 之前(`98fa634` / `ce0ee3c` / `b0a2813` 等 Phase 2 commits)。

- [ ] **Step 2: 确认 Phase 1 + Phase 2 已落地**

```bash
git log --oneline -10 | Select-String "libsql-cleanup-phase|init_db_session_resources|_queue_\* shim"
```

Expected: 能看到 Phase 1 和 Phase 2 的合并 commits(至少 `libsql-cleanup-phase2` 一行)。

- [ ] **Step 3: 切出 Phase 3 工作分支**

```bash
git checkout -b refactor/libsql-cleanup-phase3
```

Expected: `Switched to a new branch 'refactor/libsql-cleanup-phase3'`

---

## Task 2: 后端 rename — `DbReplicaHealthResponse` → `DbSyncHealthResponse` + endpoint 改名

**Files:**
- Modify: `web/backend/schemas.py:412-435` (class + 注释)
- Modify: `web/backend/routers/ops.py:20-27, 83-149` (import / endpoint / function / docstring / response_model)

- [ ] **Step 1: 改 `web/backend/schemas.py:412-435` — class 名 + 注释**

定位 schemas.py 末尾附近的 block(行 412-435):

```python
# ---------------------------------------------------------------------------
# /api/ops/db/replica-health  — DB replica 健康快照
# ---------------------------------------------------------------------------
class DbReplicaHealthResponse(BaseModel):
    """DB replica 健康快照 — 连接状态 + 同步性能 + 数据一致性。"""
    # 连接健康
    connection_alive: bool = False
    is_cloud: bool = False
    db_path: str = ""
    sync_in_progress: bool = False
    last_sync_phase: str = ""
    # 同步性能（最近 5 分钟窗口）
    sync_p50_ms: Optional[float] = None
    sync_p95_ms: Optional[float] = None
    sync_p99_ms: Optional[float] = None
    sync_count: int = 0
    # 写队列
    write_queue_depth: int = 0
    write_total_queued: int = 0
    write_total_written: int = 0
    write_total_errors: int = 0
    # 数据一致性
    schema_version: int = 0
    db_size_mb: float = 0.0
```

→ 整段替换为:

```python
# ---------------------------------------------------------------------------
# /api/ops/db/sync-health  — DB 同步健康快照 (pyturso push/pull)
# ---------------------------------------------------------------------------
class DbSyncHealthResponse(BaseModel):
    """DB 同步健康快照 — 连接状态 + 同步性能 + 数据一致性。"""
    # 连接健康
    connection_alive: bool = False
    is_cloud: bool = False
    db_path: str = ""
    sync_in_progress: bool = False
    last_sync_phase: str = ""
    # 同步性能（最近 5 分钟窗口）
    sync_p50_ms: Optional[float] = None
    sync_p95_ms: Optional[float] = None
    sync_p99_ms: Optional[float] = None
    sync_count: int = 0
    # 写队列
    write_queue_depth: int = 0
    write_total_queued: int = 0
    write_total_written: int = 0
    write_total_errors: int = 0
    # 数据一致性
    schema_version: int = 0
    db_size_mb: float = 0.0
```

字段定义完全不动 (前端 TS 接口字段名是一致的，已在 Task 3 同步改 TS interface 名)。

- [ ] **Step 2: 改 `web/backend/routers/ops.py:20-27` — import**

```python
from web.backend.schemas import (
    ApiResponse,
    DbReplicaHealthResponse,
    MetricPercentiles,
    OpsMetricsResetResponse,
    OpsMetricsResponse,
    ok_response,
)
```

→

```python
from web.backend.schemas import (
    ApiResponse,
    DbSyncHealthResponse,
    MetricPercentiles,
    OpsMetricsResetResponse,
    OpsMetricsResponse,
    ok_response,
)
```

- [ ] **Step 3: 改 `web/backend/routers/ops.py:83-87` — endpoint + function 名 + docstring**

```python
@router.get("/db/replica-health", response_model=ApiResponse[DbReplicaHealthResponse])
async def db_replica_health(
    profile: Optional[str] = Query(default=None),
):
    """DB replica 健康快照：连接 + 同步性能 + 数据一致性。"""
```

→

```python
@router.get("/db/sync-health", response_model=ApiResponse[DbSyncHealthResponse])
async def db_sync_health(
    profile: Optional[str] = Query(default=None),
):
    """DB 同步健康快照 (pyturso push/pull)：连接 + 同步性能 + 数据一致性。"""
```

- [ ] **Step 4: 改 `web/backend/routers/ops.py:133` — return 类型**

```python
    return ok_response(DbReplicaHealthResponse(
```

→

```python
    return ok_response(DbSyncHealthResponse(
```

- [ ] **Step 5: 确认全文件 0 处遗漏旧名**

```bash
git grep -n "DbReplicaHealthResponse\|db_replica_health\|/db/replica-health" web/backend/
```

Expected: **无输出**。

- [ ] **Step 6: py_compile 验证语法**

```bash
python -m py_compile web/backend/schemas.py web/backend/routers/ops.py
```

Expected: no output (退出码 0)。

- [ ] **Step 7: 跑后端单元测试**

```bash
python -m pytest tests/ -m "not slow" -q --tb=short -k "schemas or ops or routers" 2>&1 | Select-Object -Last 10
```

Expected: 0 失败 (没有针对 DbReplicaHealthResponse / endpoint 的强测试,如果有则需要更新 — 见 Step 8)。

- [ ] **Step 8: 检查测试里是否硬编码了旧名**

```bash
git grep -n "DbReplicaHealthResponse\|db_replica_health\|/db/replica-health" tests/
```

如有命中 → 同步把测试里的引用改为 `DbSyncHealthResponse` / `db_sync_health` / `/db/sync-health`,然后回到 Step 7 重跑。
如无命中 → 继续 Step 9。

- [ ] **Step 9: 提交 C1**

```bash
git add web/backend/schemas.py web/backend/routers/ops.py
git commit -m "refactor(web/backend): rename DbReplicaHealthResponse → DbSyncHealthResponse + /db/replica-health → /db/sync-health

The 'replica' name was a libsql-era term for the embedded replica health
endpoint. Post-pyturso the concept is just 'sync health' between local
SQLite file and cloud Turso DB. Renamed both the URL path and the
response schema to drop the legacy term.

Frontend will be updated in the next commit (TS interface, query key,
component file name, UI copy).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 前端 rename — TS 类型 + queryKey + SyncStatus.tsx caller

**Files:**
- Modify: `web/frontend/src/api/types.ts:297-313` (interface 名)
- Modify: `web/frontend/src/queries/queryClient.ts:63-64` (key 函数名 + cache key 字符串)
- Modify: `web/frontend/src/pages/SyncStatus.tsx:13, 32-35, 131-163` (type import + 变量名 + URL + UI 文案)

- [ ] **Step 1: 改 `web/frontend/src/api/types.ts:297-313` — interface 名**

```typescript
export interface DbReplicaHealthResponse {
  connection_alive: boolean
  is_cloud: boolean
  db_path: string
  sync_in_progress: boolean
  last_sync_phase: string
  sync_p50_ms: number | null
  sync_p95_ms: number | null
  sync_p99_ms: number | null
  sync_count: number
  write_queue_depth: number
  write_total_queued: number
  write_total_written: number
  write_total_errors: number
  schema_version: number
  db_size_mb: number
}
```

→ 把 interface 名改为 `DbSyncHealthResponse`,其余完全不动:

```typescript
export interface DbSyncHealthResponse {
  connection_alive: boolean
  is_cloud: boolean
  db_path: string
  sync_in_progress: boolean
  last_sync_phase: string
  sync_p50_ms: number | null
  sync_p95_ms: number | null
  sync_p99_ms: number | null
  sync_count: number
  write_queue_depth: number
  write_total_queued: number
  write_total_written: number
  write_total_errors: number
  schema_version: number
  db_size_mb: number
}
```

- [ ] **Step 2: 改 `web/frontend/src/queries/queryClient.ts:63-64` — key 函数名 + cache key**

```typescript
  dbReplicaHealth: (profile: string = activeProfile()) =>
    ['db_replica_health', profile] as const,
```

→

```typescript
  dbSyncHealth: (profile: string = activeProfile()) =>
    ['db_sync_health', profile] as const,
```

注意:cache key 字符串(`'db_replica_health'` → `'db_sync_health'`)也要改 — 不改会导致旧缓存条目和新条目共存,旧条目永不失效。

- [ ] **Step 3: 改 `web/frontend/src/pages/SyncStatus.tsx:13` — type import**

```typescript
import type { SyncStatusResponse, DbReplicaHealthResponse } from '../api/types'
```

→

```typescript
import type { SyncStatusResponse, DbSyncHealthResponse } from '../api/types'
```

- [ ] **Step 4: 改 `web/frontend/src/pages/SyncStatus.tsx:32-35` — useQuery 块**

```typescript
  const { data: replicaHealth } = useQuery({
    queryKey: queryKeys.dbReplicaHealth(),
    queryFn: async () => {
      const r = await apiClient<DbReplicaHealthResponse>('/api/ops/db/replica-health')
```

→

```typescript
  const { data: syncHealth } = useQuery({
    queryKey: queryKeys.dbSyncHealth(),
    queryFn: async () => {
      const r = await apiClient<DbSyncHealthResponse>('/api/ops/db/sync-health')
```

- [ ] **Step 5: 改 `web/frontend/src/pages/SyncStatus.tsx:131-163` — 全文件 `replicaHealth` → `syncHealth`**

在编辑器里把 SyncStatus.tsx 下半段(从 `{replicaHealth && (` 开始到该 block 结束)的所有 `replicaHealth.` 替换为 `syncHealth.`。

用 ripgrep 验证替换完整(无遗漏):

```bash
git grep -n "replicaHealth" web/frontend/src/pages/SyncStatus.tsx
```

Expected: **无输出**。

如果某行 UI 文案里还有 "DB 已连接" / "DB 断开" 这类带"DB"前缀的字样,**保留** — Phase 3 不动 UI 文案里的"DB"两字,只移除 "副本" 字样。当前 SyncStatus.tsx:142 显示的就是 `'DB 已连接' : 'DB 断开'`,无需改动。

- [ ] **Step 6: 全工程确认 0 处遗漏旧 TS 名**

```bash
git grep -n "DbReplicaHealthResponse\|dbReplicaHealth\|replica-health" web/frontend/src/
```

Expected: **无输出**(包括 `db_replica_health` cache key 字符串也得是 0)。

如果有命中除以下场景外的位置 → 修掉再回来:

- 命中 `web/frontend/src/components/ops/DbReplicaCard.tsx` → 不动,Task 4 整体重命名
- 命中 `web/frontend/src/pages/OpsMonitor.tsx` → 不动,Task 4 改组件 import

- [ ] **Step 7: TS 编译验证(不出包)**

```bash
cd web/frontend && npm run typecheck 2>&1 | Select-Object -Last 12
```

(如果 `package.json` 里没有 `typecheck` script,改为:)

```bash
cd web/frontend && npx tsc --noEmit 2>&1 | Select-Object -Last 12
```

Expected:0 类型错误。如果 DbReplicaCard.tsx (尚未在本 Task 改) 里引用了旧 `DbReplicaHealthResponse` 名,会报 TS error。这是预期的 — 留到 Task 4 一并解决。这里检查的是:除了 DbReplicaCard.tsx 之外没有其他 TS 错误。

如果看到的错误**仅**指向 `web/frontend/src/components/ops/DbReplicaCard.tsx` → 继续 Step 8。
如果看到其他文件的 TS 错误 → 修掉再回 Step 7 重跑。

回到工程根目录:

```bash
cd ../..
```

- [ ] **Step 8: 暂不 commit,合并进 Task 4 一起 commit**

不在此处 commit — 因为 DbReplicaCard.tsx 还在引用旧的 `DbReplicaHealthResponse`,会让 build 暂时断裂。Task 4 改完后整体一起 commit。

---

## Task 4: 前端 rename — `DbReplicaCard.tsx` → `DbSyncCard.tsx` + UI 文案

**Files:**
- Rename (git mv): `web/frontend/src/components/ops/DbReplicaCard.tsx` → `DbSyncCard.tsx`
- Modify (after rename): `web/frontend/src/components/ops/DbSyncCard.tsx:1-13, 33, 52, 64, 80`
- Modify: `web/frontend/src/pages/OpsMonitor.tsx:27, 327`

- [ ] **Step 1: git mv 重命名文件**

```bash
git mv web/frontend/src/components/ops/DbReplicaCard.tsx web/frontend/src/components/ops/DbSyncCard.tsx
```

Expected: git 把它当 rename(不是 delete+add),后续 diff 会清晰显示内容变化。

- [ ] **Step 2: 改 `DbSyncCard.tsx` 顶部注释 (行 1-5)**

```typescript
/**
 * components/ops/DbReplicaCard.tsx — Embedded Replica 健康卡片。
 *
 * 展示：连接状态、同步性能 p50/p95、写队列、schema 版本、DB 大小。
 */
```

→

```typescript
/**
 * components/ops/DbSyncCard.tsx — DB 同步健康卡片 (pyturso push/pull)。
 *
 * 展示：连接状态、同步性能 p50/p95、写队列、schema 版本、DB 大小。
 */
```

- [ ] **Step 3: 改 `DbSyncCard.tsx` import (行 13)**

```typescript
import type { DbReplicaHealthResponse } from '../../api/types'
```

→

```typescript
import type { DbSyncHealthResponse } from '../../api/types'
```

- [ ] **Step 4: 改 `DbSyncCard.tsx` 默认 export 函数名 (行 33) + queryKey (行 35) + queryFn 内 type 与 URL (行 36-40)**

```typescript
export default function DbReplicaCard({ profile }: { profile: string }) {
  const { data, error, isFetching } = useQuery({
    queryKey: queryKeys.dbReplicaHealth(profile),
    queryFn: async () => {
      const res = await apiClient<DbReplicaHealthResponse>(
        `/api/ops/db/replica-health?profile=${encodeURIComponent(profile)}`,
      )
      return res.data
    },
```

→

```typescript
export default function DbSyncCard({ profile }: { profile: string }) {
  const { data, error, isFetching } = useQuery({
    queryKey: queryKeys.dbSyncHealth(profile),
    queryFn: async () => {
      const res = await apiClient<DbSyncHealthResponse>(
        `/api/ops/db/sync-health?profile=${encodeURIComponent(profile)}`,
      )
      return res.data
    },
```

- [ ] **Step 5: 改 `DbSyncCard.tsx` UI 标题文案 ("DB 副本健康" → "DB 同步健康") — 行 52, 64, 80**

每个 `<h3>` 标签里的文案 "DB 副本健康" 都要改。先看 git grep:

```bash
git grep -n "DB 副本健康" web/frontend/src/components/ops/DbSyncCard.tsx
```

Expected: 命中 3 行(error 占位 / loading 占位 / 主卡片标题)。

逐行 (~52, ~64, ~80) 把字符串 `"DB 副本健康"` 改为 `"DB 同步健康"`。

替换示例:

```typescript
          <h3 className="font-medium text-sm text-text-primary">DB 副本健康</h3>
```

→

```typescript
          <h3 className="font-medium text-sm text-text-primary">DB 同步健康</h3>
```

(三处都改,文本完全相同,只字串内容变化)

- [ ] **Step 6: 改 `web/frontend/src/pages/OpsMonitor.tsx:27, 327` — import + JSX 使用**

第 27 行 import:

```typescript
import DbReplicaCard from '../components/ops/DbReplicaCard'
```

→

```typescript
import DbSyncCard from '../components/ops/DbSyncCard'
```

第 327 行 JSX:

```typescript
        <DbReplicaCard profile={activeProfile ?? ''} />
```

→

```typescript
        <DbSyncCard profile={activeProfile ?? ''} />
```

- [ ] **Step 7: grep 审计前端全 0**

```bash
git grep -in "DbReplica\|replica-health\|dbReplicaHealth\|db_replica_health\|DB 副本健康\|嵌入式副本" web/frontend/
```

Expected: **无输出**。

(注意 `-i` 大小写不敏感 —— 防止漏掉 `dbReplicaHealth` 或 `DBREPLICACARD` 等变体。)

如果命中 `web/frontend/src/components/ops/DbReplicaCard.tsx` 字样 → 检查是不是 git mv 之后旧引用还在 (不应该)。

- [ ] **Step 8: 前端 build 验证**

```bash
cd web/frontend && npm run build 2>&1 | Select-Object -Last 15
```

Expected: build 成功,无 TS error,vite 输出 `dist/` 文件。

回到工程根目录:

```bash
cd ../..
```

- [ ] **Step 9: 后端 + 前端联动端到端 smoke test**

启动 web (开发模式同时跑后端 + 前端 dev server):

```bash
python scripts/start_web.py --dev
```

观察控制台:
- backend banner 出来 (`Uvicorn running on http://127.0.0.1:8765`)
- frontend vite dev server 起来 (`Local: http://localhost:5173`)
- 浏览器打开 `http://localhost:5173`
- 登录任一已配置的 profile
- 导航到 OpsMonitor 页 → 找到 "DB 同步健康" 卡片
- 卡片正常显示 (即使数据为空,UI 不报错)
- 浏览器 DevTools Network 面板 → 看到 `GET /api/ops/db/sync-health?profile=...` 返回 200,响应 body 符合 `DbSyncHealthResponse` 字段
- Ctrl+C 关掉 dev server

- [ ] **Step 10: 提交 C2 (Task 3 + Task 4 合并一个 commit)**

```bash
git add web/frontend/src/api/types.ts web/frontend/src/queries/queryClient.ts web/frontend/src/pages/SyncStatus.tsx web/frontend/src/pages/OpsMonitor.tsx web/frontend/src/components/ops/DbSyncCard.tsx
git commit -m "refactor(web/frontend): rename DbReplicaCard → DbSyncCard + drop 'replica' from UI surface

Frontend half of the libsql 'embedded replica' → pyturso sync rename:

- DbReplicaHealthResponse TS interface → DbSyncHealthResponse
- queryKeys.dbReplicaHealth → queryKeys.dbSyncHealth (cache key 'db_replica_health' → 'db_sync_health'; old cached entries would otherwise live forever in the QueryClient)
- API URL '/api/ops/db/replica-health' → '/api/ops/db/sync-health' (matches backend rename in the previous commit)
- Component file DbReplicaCard.tsx → DbSyncCard.tsx (git mv preserves history)
- UI copy 'DB 副本健康' → 'DB 同步健康' (3 occurrences in DbSyncCard: error / loading / main)
- OpsMonitor.tsx import + JSX updated
- SyncStatus.tsx variable 'replicaHealth' → 'syncHealth' throughout

No data-shape changes — DbSyncHealthResponse has identical fields to the old interface.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 拆分 `database/connection.py` (725 行) 为 `database/connection/` 包

**Files:**
- Create: `database/connection/__init__.py` (~60 行,re-exports)
- Create: `database/connection/context.py` (~170 行,纯助手)
- Create: `database/connection/factory.py` (~310 行,连接工厂)
- Create: `database/connection/singleton.py` (~220 行,写单例)
- Delete: `database/connection.py` (整文件)
- Modify: `web/backend/routers/ops.py:95` (单例可变全局 import 改为子模块直读)

### 拆分策略

把 725 行单文件按"职责"切成 4 块,通过 `__init__.py` re-export 保持 `from database.connection import X` 全部继续工作:

| 子模块 | 包含的函数 | 原 connection.py 行段 |
|---|---|---|
| `context.py` | 模块常量 / `_get_backend` / `_debug_log` / `register_schema_initializers` / `_is_main_db_path` / `_is_hub_db_path` / `_is_replica_metadata_missing_error` / `_resolve_conn_context` / `_row_to_dict` | 1-176 + 639-655 |
| `factory.py` | `_get_local_read_conn` / `_get_local_conn` / `_get_hub_local_conn` / `_get_hub_conn` / `_should_use_local_only_connection` / `_wrap_and_track_connection` / `_get_read_conn` / `_get_read_conn_impl` / `_get_conn` / `_run_with_managed_connection` / `_hub_fetch_one_dict` / `_hub_fetch_all_dicts` / `is_hub_configured` / `set_runtime_cloud_credentials` | 213-332 + 481-601 + 618-716 |
| `singleton.py` | 写单例 globals + `_close_main_write_conn_singleton` / `_close_hub_write_conn_singleton` / `_get_main_write_conn_singleton` / `_get_hub_write_conn_singleton` / `_get_dedicated_write_conn` | 78-86 + 178-211 + 334-478 + 602-616 |
| `__init__.py` | re-export 全部公共名 (含从 `database.execution_engine` 转发的 4 个) | (新建) |

**循环依赖处理**:`factory.py` 里 `_get_conn` / `_get_hub_conn` 需要 `_get_main_write_conn_singleton` / `_get_hub_write_conn_singleton`(从 `singleton.py`),`singleton.py` 又需要 `_get_local_conn` / `_get_hub_local_conn`(从 `factory.py`)。解决:`singleton.py` 在模块顶部 import factory(单向),`factory.py` 里需要单例的位置改为**函数体内 late import**(不在模块顶部 import singleton)。

**可变全局**:写单例 globals (`_main_write_conn_singleton` 等) 只能住在它们被 `global` 修改的那个模块(`singleton.py`)。`__init__.py` 不能 `from .singleton import _main_write_conn_singleton` re-export,因为那是值快照,后续 mutation 看不到。**唯一一个真正读这些 globals 的外部消费者** 是 `web/backend/routers/ops.py:95`,直接改它从 `database.connection.singleton` 子模块拿即可。

- [ ] **Step 1: 创建 `database/connection/` 目录与 `context.py`**

新建空文件 `database/connection/context.py`,粘贴以下完整内容:

```python
from __future__ import annotations
"""database/connection/context.py: 连接管理的纯助手层。

包含模块级常量、backend 单例、日志助手、路径谓词、连接上下文解析等
**不持有可变状态、不调用其他子模块** 的辅助代码。

`factory.py` 与 `singleton.py` 都 import 自这里。它本身只 import 自
`database.backends` / `database.utils` / `core.logger`,无任何环依赖。
"""

import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple  # noqa: F401 (re-export)

import config as _config

HUB_DB_PATH = _config.HUB_DB_PATH  # Hub 是全局静态库，不随 switch_user 变化，可缓存
TURSO_HUB_AUTH_TOKEN = _config.TURSO_HUB_AUTH_TOKEN
TURSO_HUB_DB_URL = _config.TURSO_HUB_DB_URL

# 注意：DB_PATH 不缓存到本模块级。switch_user 不会反向 patch database 子模块的全局；
# 所有需要"当前用户 DB 路径"的位置都直接读 `_config.DB_PATH`。

from database.backends import get_active_backend, HAS_PYTURSO

_backend = None  # Lazy init
_backend_lock = threading.Lock()


def _get_backend():
    global _backend
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                _backend = get_active_backend()
    return _backend


try:
    from core.logger import get_logger
except ImportError:
    try:
        from .logger import get_logger  # type: ignore
    except ImportError:
        import logging

        def get_logger():
            return logging.getLogger(__name__)


from database.utils import (
    _backup_broken_database_file,
    _is_sqlite_data_corruption_error,
    _is_sqlite_malformed_error,
    _normalize_turso_url,
)


TURSO_TEST_DB_URL = os.getenv("TURSO_TEST_DB_URL")
TURSO_TEST_AUTH_TOKEN = os.getenv("TURSO_TEST_AUTH_TOKEN")
TURSO_TEST_DB_HOSTNAME = os.getenv("TURSO_TEST_DB_HOSTNAME")


# Schema callback registry to avoid circular imports with database/schema.py
_schema_init_callbacks: Dict[str, Optional[Callable[[Any], None]]] = {
    "main": None,
    "hub": None,
}


def register_schema_initializers(
    main_initializer: Optional[Callable[[Any], None]] = None,
    hub_initializer: Optional[Callable[[Any], None]] = None,
) -> None:
    """Register schema initialization callbacks lazily.

    This avoids importing business/schema modules from connection.* directly.
    """
    if main_initializer is not None:
        _schema_init_callbacks["main"] = main_initializer
    if hub_initializer is not None:
        _schema_init_callbacks["hub"] = hub_initializer


def _debug_log(msg: str, start_time: Optional[float] = None, level: str = "DEBUG") -> None:
    elapsed = f" | Time: {int((time.time() - start_time) * 1000)}ms" if start_time else ""
    text = f"{msg}{elapsed}"
    try:
        logger = get_logger()
        func = getattr(logger, level.lower(), None)
        if callable(func):
            try:
                func(text, module="database.connection")
            except TypeError:
                func(text)
        else:
            logger.debug(text)
    except Exception:
        pass


def _is_main_db_path(db_path: Optional[str] = None) -> bool:
    # Snapshot DB_PATH once to avoid TOCTOU race with prepare_for_task() patching
    current_db_path = _config.DB_PATH
    target = os.path.abspath(db_path or current_db_path)
    return target == os.path.abspath(current_db_path)


def _is_hub_db_path(db_path: Optional[str] = None) -> bool:
    target = os.path.abspath(db_path or HUB_DB_PATH)
    return target == os.path.abspath(HUB_DB_PATH)


def _is_replica_metadata_missing_error(error: Exception) -> bool:
    return False


def _resolve_conn_context(db_path: Optional[str] = None) -> Dict[str, Any]:
    path = db_path or _config.DB_PATH
    target_abs = os.path.abspath(path)
    main_abs = os.path.abspath(_config.DB_PATH)

    url = os.getenv("TURSO_DB_URL")
    token = os.getenv("TURSO_AUTH_TOKEN")
    hostname = os.getenv("TURSO_DB_HOSTNAME")

    if not url and hostname:
        url = _normalize_turso_url(hostname)

    is_test = bool(db_path and ("test_" in os.path.basename(db_path) or "test-" in os.path.basename(db_path)))
    if is_test:
        url = os.getenv("TURSO_TEST_DB_URL") or url
        token = os.getenv("TURSO_TEST_AUTH_TOKEN") or token

    from config import get_force_cloud_mode

    force_cloud_mode = bool(get_force_cloud_mode())
    if force_cloud_mode and not url:
        _debug_log("强制云端模式启用，但未发现 TURSO_DB_URL", level="WARNING")

    return {
        "db_path": path,
        "is_main_db": target_abs == main_abs,
        "is_test": is_test,
        "url": url,
        "token": token,
        "force_cloud_mode": force_cloud_mode,
    }


def _row_to_dict(cursor: Any, row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return row
    if hasattr(row, "asdict"):
        try:
            return row.asdict()
        except Exception:
            pass

    try:
        return dict(zip(row.keys(), tuple(row)))
    except AttributeError:
        if hasattr(row, "astuple") and hasattr(cursor, "description") and cursor.description:
            cols = [d[0] for d in cursor.description]
            return dict(zip(cols, row.astuple()))
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))
```

验证语法:

```bash
python -m py_compile database/connection/context.py
```

Expected: no output。

> 注:目录 `database/connection/` 此时**还不是**一个有效 Python 包(缺 `__init__.py`),但 `python -m py_compile` 只看单文件,不会报。

- [ ] **Step 2: 创建 `database/connection/factory.py`**

新建文件 `database/connection/factory.py`,粘贴以下顶部:

```python
from __future__ import annotations
"""database/connection/factory.py: 连接工厂与读路径分发。

按"如何打开一条连接"的职责切片:
- 本地连接: _get_local_conn / _get_local_read_conn / _get_hub_local_conn
- 云端 Hub: _get_hub_conn (cloud-or-local 自适应)
- 读路径分发: _get_read_conn / _get_read_conn_impl / _should_use_local_only_connection
- 通用 getter: _get_conn (do_sync=True 才走单例)
- 业务工具: _run_with_managed_connection / _hub_fetch_one_dict / _hub_fetch_all_dicts
- 兜底声明: is_hub_configured / set_runtime_cloud_credentials

依赖方向:本模块只 import 自 `context`,不 import 自 `singleton`。需要写单例
的位置(`_get_conn` 的 do_sync 路径、`_get_hub_conn`)走**函数体内 late import**
避免循环 import。
"""

import os
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional, Tuple  # noqa: F401

import config as _config

from .context import (
    HAS_PYTURSO,
    HUB_DB_PATH,
    TURSO_HUB_AUTH_TOKEN,
    TURSO_HUB_DB_URL,
    _backup_broken_database_file,
    _debug_log,
    _get_backend,
    _is_main_db_path,
    _is_sqlite_data_corruption_error,
    _is_sqlite_malformed_error,
    _resolve_conn_context,
    _row_to_dict,
    _schema_init_callbacks,
    get_logger,
)
```

然后逐段**复制**以下函数体(完整 def 块,保留原有缩进与注释)从原 `database/connection.py` 到 `database/connection/factory.py` 末尾:

| 函数 | 原 connection.py 行段 |
|---|---|
| `_get_local_read_conn` | 213-238 |
| `_get_local_conn` | 241-289 |
| `_get_hub_local_conn` | 290-332 |
| `_should_use_local_only_connection` | 481-490 |
| `_wrap_and_track_connection` | 493-494 |
| `_get_read_conn` | 497-508 |
| `_get_read_conn_impl` | 511-539 |
| `_get_conn` | 542-557 |
| `is_hub_configured` | 560-561 |
| `_get_hub_conn` | 564-599 |
| `_run_with_managed_connection` | 618-636 |
| `_hub_fetch_one_dict` | 658-683 |
| `_hub_fetch_all_dicts` | 686-711 |
| `set_runtime_cloud_credentials` | 714-715 |

复制时**注意改 4 处**(从直接 import 变成 late import,因为 singleton 在 sibling 模块):

a. `_get_local_conn` 函数体内,行 ~274 处的 `_get_conn(path, allow_local_fallback=False)` — 这是同模块内调用,**不动**(都在 factory.py 里)。

b. `_get_conn` 函数体内,原行 ~554 处:

```python
        return _get_main_write_conn_singleton(do_sync=do_sync, max_retries=max_retries, retry_delay=retry_delay)
```

改为(函数体内 late import):

```python
        from .singleton import _get_main_write_conn_singleton
        return _get_main_write_conn_singleton(do_sync=do_sync, max_retries=max_retries, retry_delay=retry_delay)
```

c. `_get_hub_conn` 函数体内,原行 ~578 处:

```python
                result = _get_hub_write_conn_singleton(
                    do_sync=False,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                )
```

改为:

```python
                from .singleton import _get_hub_write_conn_singleton
                result = _get_hub_write_conn_singleton(
                    do_sync=False,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                )
```

d. 检查 `_hub_fetch_one_dict` / `_hub_fetch_all_dicts` 是否需要类似处理 — 它们调用 `_get_hub_local_conn`(同模块,**不动**)。

验证语法:

```bash
python -m py_compile database/connection/factory.py
```

Expected: no output。

- [ ] **Step 3: 创建 `database/connection/singleton.py`**

新建文件 `database/connection/singleton.py`,粘贴以下顶部:

```python
from __future__ import annotations
"""database/connection/singleton.py: 写连接单例 (主库 + Hub) 与其消费者。

pyturso 下写单例只在 `do_sync=True` 窄路径有意义 —— 即 init_db 的首次连接
与 do_sync_on(conn) 的显式触发,避免每次都重建一个 80~141s bootstrap
的连接。其他写路径走 `factory.py` 的 _get_local_conn 现开新连接 (MVCC
下安全,libsql 时代为避 WAL 互斥才必须用 singleton)。

依赖方向:本模块 import 自 `context`(纯助手) + `factory`(连接工厂)。
**factory 不反向 import 本模块**,只在函数体里 late import 才打破环。

模块级可变 globals (`_main_write_conn_singleton` 等) 的真实读取必须通过
本模块的属性访问 (`database.connection.singleton._main_write_conn_singleton`),
不能走 `from database.connection import _main_write_conn_singleton`(那会
变快照)。__init__.py 不 re-export 这些 globals,唯一外部消费者
(`web/backend/routers/ops.py`) 直接 import 本子模块。
"""

import os
import threading
import time
from typing import Any, Optional

import config as _config

from .context import (
    HAS_PYTURSO,
    HUB_DB_PATH,
    TURSO_HUB_AUTH_TOKEN,
    TURSO_HUB_DB_URL,
    _backup_broken_database_file,
    _debug_log,
    _get_backend,
    _is_sqlite_malformed_error,
    _resolve_conn_context,
)
from .factory import _get_local_conn, _get_hub_local_conn


# ---- write singleton 模块级状态 ----
_main_write_conn_singleton: Any = None
_main_write_conn_singleton_path: Optional[str] = None
_main_write_conn_last_check: float = 0
_main_write_conn_lock = threading.Lock()
_main_write_conn_init_lock = threading.Lock()

_hub_write_conn_singleton: Any = None
_hub_write_conn_lock = threading.Lock()
_hub_write_conn_init_lock = threading.Lock()
```

然后**复制**以下函数(完整 def 块,保留原缩进)从原 `database/connection.py` 到 `database/connection/singleton.py` 末尾:

| 函数 | 原 connection.py 行段 |
|---|---|
| `_close_main_write_conn_singleton` | 178-192 |
| `_close_hub_write_conn_singleton` | 195-208 |
| `_get_main_write_conn_singleton` | 334-412 |
| `_get_hub_write_conn_singleton` | 416-478 |
| `_get_dedicated_write_conn` | 602-615 |

复制时**注意 1 处**:`_get_dedicated_write_conn` 调用 `_get_local_conn`(已经从 `.factory` import 进来,不动)。

验证语法:

```bash
python -m py_compile database/connection/singleton.py
```

Expected: no output。

- [ ] **Step 4: 创建 `database/connection/__init__.py` (re-exports)**

新建文件 `database/connection/__init__.py`,粘贴以下完整内容:

```python
from __future__ import annotations
"""database/connection — 连接管理包 (拆自原 single-file connection.py)。

子模块职责:
- context.py   纯助手 (路径谓词、上下文解析、日志、backend 获取)
- factory.py   连接工厂 (本地/云端/Hub 连接打开 + 读路径分发)
- singleton.py 写单例 (主库与 Hub 的长期持有连接)

外部 import 兼容:`from database.connection import _get_local_conn` 等原有
写法继续可用,本 __init__ 透明 re-export。**例外**:
`_main_write_conn_singleton` / `_main_write_conn_singleton_path` /
`_hub_write_conn_singleton` 是模块级可变 globals,Python `from … import`
会拿快照,故 **不在此处 re-export**;直接读它们的位置(如
`web/backend/routers/ops.py`)必须 `from database.connection.singleton
import _main_write_conn_singleton`。
"""

# 纯助手与谓词
from .context import (
    HAS_PYTURSO,
    HUB_DB_PATH,
    TURSO_HUB_AUTH_TOKEN,
    TURSO_HUB_DB_URL,
    TURSO_TEST_AUTH_TOKEN,
    TURSO_TEST_DB_HOSTNAME,
    TURSO_TEST_DB_URL,
    _debug_log,
    _get_backend,
    _is_hub_db_path,
    _is_main_db_path,
    _is_replica_metadata_missing_error,
    _resolve_conn_context,
    _row_to_dict,
    _schema_init_callbacks,
    get_logger,
    register_schema_initializers,
)

# 连接工厂与读路径
from .factory import (
    _get_conn,
    _get_hub_conn,
    _get_hub_local_conn,
    _get_local_conn,
    _get_local_read_conn,
    _get_read_conn,
    _get_read_conn_impl,
    _hub_fetch_all_dicts,
    _hub_fetch_one_dict,
    _run_with_managed_connection,
    _should_use_local_only_connection,
    _wrap_and_track_connection,
    is_hub_configured,
    set_runtime_cloud_credentials,
)

# 写单例 — 仅函数;模块级可变 globals 故意不 re-export (见上方注释)
from .singleton import (
    _close_hub_write_conn_singleton,
    _close_main_write_conn_singleton,
    _get_dedicated_write_conn,
    _get_hub_write_conn_singleton,
    _get_main_write_conn_singleton,
)

# 转发自 database.execution_engine — 维持原 connection.py 末尾的 re-export 行为
# 消费者:
#   - database/_repo_helpers.py 访问 2 个 _execute_* 名
#   - core/study_flow.py 访问 init_db_session_resources / cleanup_db_session_resources
from database.execution_engine import (
    _execute_batch_write_sql_sync,
    _execute_write_sql_sync,
    cleanup_db_session_resources,
    init_db_session_resources,
)
```

验证 import:

```bash
python -m py_compile database/connection/__init__.py
```

如果 py_compile 此时报错说 `database.connection.factory` 找不到 → 因为旧 `database/connection.py` 还在,Python 优先解析为文件。继续 Step 5 删旧文件。

- [ ] **Step 5: 删除旧 `database/connection.py` 单文件**

```bash
git rm database/connection.py
```

Expected: `rm 'database/connection.py'`。

> 注:`git rm` 会同时从工作区与 index 删除。此时 `database/connection/` 包就是 `database.connection` 模块的唯一来源。

- [ ] **Step 6: 第一轮整体 import 验证 (不跑业务)**

```bash
python -c "from database import connection as c; print('package import ok:', c.__file__)"
python -c "from database.connection import _get_local_conn, _get_read_conn, _get_main_write_conn_singleton, _execute_write_sql_sync; print('re-exports ok')"
python -c "from database.connection.singleton import _main_write_conn_singleton, _main_write_conn_singleton_path; print('singleton submodule import ok')"
```

Expected:
- 第一行: `package import ok: <path>/database/connection/__init__.py`
- 第二行: `re-exports ok`
- 第三行: `singleton submodule import ok`

如有 ImportError → 看具体哪个名漏了 re-export,补到 `__init__.py`。
如有循环 import → 把 factory.py 里残留的顶层 `from .singleton import …` 移到函数体内 late import。

- [ ] **Step 7: 更新 `web/backend/routers/ops.py:95` — 单例可变全局改子模块直读**

定位 `db_sync_health` 函数(C1 改名后)体内,接近开头处:

```python
    # 连接健康
    from database.connection import _main_write_conn_singleton, _main_write_conn_singleton_path
    conn_alive = _main_write_conn_singleton is not None
    is_cloud = bool(os.getenv("TURSO_DB_URL"))
    db_path = _main_write_conn_singleton_path or ""
```

→ 改为:

```python
    # 连接健康 (singleton globals 必须直读子模块,见 database/connection/singleton.py 头部注释)
    from database.connection.singleton import (
        _main_write_conn_singleton,
        _main_write_conn_singleton_path,
    )
    conn_alive = _main_write_conn_singleton is not None
    is_cloud = bool(os.getenv("TURSO_DB_URL"))
    db_path = _main_write_conn_singleton_path or ""
```

> 重要:这个 import 在函数体内,每次 endpoint 调用都重新查找 `sys.modules['database.connection.singleton']._main_write_conn_singleton` 当前值,不会被快照住。

- [ ] **Step 8: grep 审计 — 其他位置如果也直读了可变 globals 需一并改**

```bash
git grep -n "from database.connection import .*_main_write_conn_singleton\|from database.connection import .*_main_write_conn_singleton_path\|from database.connection import .*_hub_write_conn_singleton[^_]"
```

Expected: 仅命中 `web/backend/routers/ops.py`(刚才改过的)。

如果命中其他文件 → 同样改成 `from database.connection.singleton import …`。

(注意正则 `_hub_write_conn_singleton[^_]` 是排除掉 `_hub_write_conn_singleton_lock` / `_get_hub_write_conn_singleton` 这种带尾缀/前缀的合法名。)

- [ ] **Step 9: 全套 pytest**

```bash
python -m pytest tests/ -m "not slow" -q --tb=short 2>&1 | Select-Object -Last 15
```

Expected: 全过。

如出现 `ImportError: cannot import name X from database.connection` → 把 X 加到 `database/connection/__init__.py` 对应子模块的 import 块。

如出现 `AttributeError: module 'database.connection' has no attribute X` 而 X 是被 `database.connection.X = ...` 这种方式 monkeypatch 的 — 该模块属性赋值是发生在 `__init__.py` 的 namespace,不会传到子模块。这种情况罕见,如真发生:检查测试 fixtures (例如 `tests/conftest.py:8` 的 `import database.connection as db_connection`,以及 `tests/web/test_users.py:59` 的 `import database.connection as db_conn`),它们如果做 `db_connection.cleanup_db_session_resources = ...` 这种 monkeypatch 没问题(函数是同一对象);如果做 `db_conn._main_write_conn_singleton = X` 这种**可变 global 赋值**则需要改成 `db_conn.singleton._main_write_conn_singleton = X` 或 monkeypatch 子模块。

- [ ] **Step 10: 端到端 smoke test**

```bash
python scripts/start_web.py
```

观察:
- backend 启动 banner(没有 import 报错)
- `curl http://127.0.0.1:8765/api/health` 返回 200(或浏览器打开看到 health JSON)
- `curl 'http://127.0.0.1:8765/api/ops/db/sync-health?profile=<your-profile>'` 返回 200 + 合法 `DbSyncHealthResponse` JSON(`connection_alive` / `db_path` / `sync_p50_ms` 等字段齐全)
- Ctrl+C 关掉

> 这是 Phase 3 最关键的端到端检查 — 拆分后 backend 必须能正常启动并响应 ops endpoint。

- [ ] **Step 11: 最终 grep 审计 + 文件清单确认**

```bash
ls database/connection/
```

Expected: 4 个文件 — `__init__.py`, `context.py`, `factory.py`, `singleton.py`。

```bash
git status
```

Expected:
- `deleted: database/connection.py`
- `new file: database/connection/__init__.py`
- `new file: database/connection/context.py`
- `new file: database/connection/factory.py`
- `new file: database/connection/singleton.py`
- `modified: web/backend/routers/ops.py`

```bash
git grep "Embedded Replica" -- "*.py" "*.tsx"
```

Expected: 仅命中归档文档(`docs/history/`、`docs/superpowers/specs/2026-05-23-libsql-residual-cleanup-design.md` 等),业务代码 0 命中。

- [ ] **Step 12: 提交 C3**

```bash
git add database/connection/ web/backend/routers/ops.py
git commit -m "refactor(database): split connection.py (725 lines) into connection/ package

The single connection.py file had grown to 725 lines mixing four
distinct concerns: pure helpers (path predicates, context resolution),
connection factories (local/cloud/hub), write singletons (long-lived
connections for do_sync), and re-exports from execution_engine.

Split into a 4-file package, keeping all existing 'from database.connection
import X' call sites working via __init__.py re-exports:

- context.py   (~170 lines) — backend init, _debug_log, path predicates,
                              _resolve_conn_context, _row_to_dict
- factory.py   (~310 lines) — _get_local_conn, _get_hub_conn, _get_conn,
                              _get_read_conn*, _hub_fetch_*; late-imports
                              from singleton to avoid circular dep
- singleton.py (~220 lines) — write singleton state + _get_main/hub_write_
                              conn_singleton + _get_dedicated_write_conn
- __init__.py  (~60 lines)  — re-exports for backward compat

Caller updates: ops.py is the only external consumer that directly
imports mutable singleton globals (_main_write_conn_singleton). Python's
'from X import Y' takes a value snapshot, so re-exporting these through
__init__ would silently freeze them at None. Updated ops.py to
'from database.connection.singleton import …' which goes via sys.modules
lookup at each call.

No behavioral change — every function moved verbatim.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: 最终验证 + 推送 + 开 PR

**Files:**
- 无文件修改

- [ ] **Step 1: 跑完整测试套件 (含 slow)**

```bash
python -m pytest tests/ -q --tb=short 2>&1 | Select-Object -Last 15
```

Expected: 全过。如果有 slow tests 失败 → 看是不是上一步漏掉的 import path / monkeypatch 问题。

- [ ] **Step 2: 前端构建复跑**

```bash
cd web/frontend && npm run build 2>&1 | Select-Object -Last 6
cd ../..
```

Expected: build 成功。

- [ ] **Step 3: 检查 commit 历史**

```bash
git log --oneline feat/web-ui..HEAD
```

Expected: 3 个 commits,从老到新:

1. `refactor(web/backend): rename DbReplicaHealthResponse → DbSyncHealthResponse + /db/replica-health → /db/sync-health`
2. `refactor(web/frontend): rename DbReplicaCard → DbSyncCard + drop 'replica' from UI surface`
3. `refactor(database): split connection.py (725 lines) into connection/ package`

- [ ] **Step 4: 跨阶段 grep 总审计**

```bash
git grep -in "DbReplica\|DbReplicaCard\|db_replica_health\|/db/replica-health\|dbReplicaHealth\|嵌入式副本"
```

Expected: 仅命中 docs 历史归档(`docs/history/`、`docs/superpowers/specs/`、`docs/superpowers/plans/2026-05-15-*`),业务代码 0 命中。

```bash
git grep -in "Embedded Replica" -- "*.py" "*.tsx" "*.ts"
```

Expected: 仅命中 `docs/superpowers/specs/2026-05-23-libsql-residual-cleanup-design.md`(spec 历史描述,正常)和归档文件。

```bash
git grep -n "from database.connection import _main_write_conn_singleton\|from database.connection import _main_write_conn_singleton_path\|from database.connection import _hub_write_conn_singleton[^_]"
```

Expected: **无输出**(都改成走 `database.connection.singleton` 子模块)。

- [ ] **Step 5: 推送并开 PR**

```bash
git push -u origin refactor/libsql-cleanup-phase3

gh pr create --title "refactor: drop 'Embedded Replica' surface + split connection.py (Phase 3)" --body "$(cat <<'EOF'
## Summary

Phase 3 of libsql residual cleanup — the final, originally-optional phase. See [design spec](docs/superpowers/specs/2026-05-23-libsql-residual-cleanup-design.md) Phase 3 section for full context.

Three logical changes, three commits:

1. **Backend rename** — `DbReplicaHealthResponse` → `DbSyncHealthResponse`; `/api/ops/db/replica-health` → `/api/ops/db/sync-health`.
2. **Frontend rename** — TS interface, queryKey, API URL caller, component file (`DbReplicaCard.tsx` → `DbSyncCard.tsx`), and the three "DB 副本健康" UI strings → "DB 同步健康".
3. **Split `connection.py`** — 725-line single file → `connection/` package: `context.py` (pure helpers) / `factory.py` (connection openers) / `singleton.py` (write singletons) / `__init__.py` (re-exports for backward compat). External callers continue to use `from database.connection import X`; the single exception is `web/backend/routers/ops.py`, which now reads write-singleton mutable globals via `from database.connection.singleton import …` (Python `from … import` would otherwise snapshot the `None` initial value).

**No behavioral changes** — every function moves verbatim; no schema changes; no field shape changes; the API/UI rename is symmetric.

## Test plan

- [x] `pytest tests/` 全套通过 (含 slow)
- [x] `npm run build` 前端构建成功
- [x] `python scripts/start_web.py` 启动 + `/api/ops/db/sync-health?profile=<x>` 返回 200 + 合法 JSON
- [x] 浏览器 OpsMonitor 页 → 看到 "DB 同步健康" 卡片 (DevTools Network 显示新 URL)
- [x] `git grep -i "DbReplica\|db_replica_health\|嵌入式副本"` 业务代码 0 命中
- [x] `git grep -i "Embedded Replica" -- "*.py" "*.tsx" "*.ts"` 业务代码 0 命中
- [x] `git grep "from database.connection import .*_main_write_conn_singleton[^_]"` 0 命中 (单例 globals 改走子模块)

## Depends on

- Phase 1 PR (libsql-cleanup-phase1) — merged
- Phase 2 PR (libsql-cleanup-phase2) — merged

## Rollback

Each commit is independently revertable:

- C3 revert → 重新走单文件 `connection.py`(用 git revert 恢复)
- C2 revert → 前端回退命名,与 C1 暂时错位(API URL 不存在) — 不要单独 revert C2
- C1 revert → API 回到旧 URL,需要同步 revert C2

如需整 PR 回滚:`git revert <merge-commit>` 一次到位。

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL 输出。

---

## Phase 3 完成检查清单

- [ ] 3 个 commit 都在 `refactor/libsql-cleanup-phase3` 分支
- [ ] `pytest tests/` 全套通过
- [ ] `npm run build` 通过
- [ ] `python scripts/start_web.py` smoke test 通过,`/api/ops/db/sync-health` endpoint 返回 200
- [ ] 浏览器 OpsMonitor 显示 "DB 同步健康" 卡片
- [ ] `git grep -i "DbReplica\|嵌入式副本\|db_replica_health"` 业务代码 0 命中
- [ ] `git grep -i "Embedded Replica" -- "*.py" "*.tsx"` 业务代码 0 命中
- [ ] `database/connection/` 包形态,4 个子文件
- [ ] PR 已开

---

## 后续:落地后的 doc 更新 (PR merged 后单独一个小 commit)

按设计 spec "落地文档" 节:

- `docs/dev/DECISIONS.md` 追加 `DEC-### Phase 3 — 'Embedded Replica' 暴露面下线 + connection.py 拆分`,说明拆分边界与可变 global 的处理决策。
- `docs/api/turso_api.md §14`(若存在)按需追加新踩坑。
- `CLAUDE.md` "模块地图" 段,把 `database/connection.py` 引用改为 `database/connection/`(描述不变,只改路径)。
- `database/README.md` 若引用具体子模块路径需同步更新(原文里有 `_get_read_conn_impl(...)` 等函数描述,只要不写死 `connection.py` 路径就不用改)。

这一步**不放在本 Phase 3 PR 内**,留作 follow-up — 否则 PR diff 噪声变大,审核负担增加。
