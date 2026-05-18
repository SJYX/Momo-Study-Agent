# DB Replica Health Indicators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Embedded Replica (local SQLite <-> Turso cloud) sync health indicators to OpsMonitor and SyncStatus pages.

**Architecture:** New backend endpoint `/api/db/replica-health` aggregates connection health, sync performance metrics, and data consistency info. OpsMonitor gets a 5th card; SyncStatus gets a top-level health banner. All data comes from existing infrastructure (no new background threads).

**Tech Stack:** FastAPI, React Query, Tailwind CSS, lucide-react icons

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `web/backend/routers/ops.py` | Modify | Add `GET /api/db/replica-health` endpoint |
| `web/backend/schemas.py` | Modify | Add `DbReplicaHealthResponse` model |
| `web/frontend/src/api/types.ts` | Modify | Add TS type for replica health |
| `web/frontend/src/queries/queryClient.ts` | Modify | Add `dbReplicaHealth` query key |
| `web/frontend/src/components/ops/DbReplicaCard.tsx` | Create | New card component for OpsMonitor |
| `web/frontend/src/pages/OpsMonitor.tsx` | Modify | Add 5th card (DbReplicaCard) |
| `web/frontend/src/pages/SyncStatus.tsx` | Modify | Add health banner at top |

---

### Task 1: Backend — Add `DbReplicaHealthResponse` schema

**Files:**
- Modify: `web/backend/schemas.py`

- [ ] **Step 1: Add the Pydantic model**

Add after `SyncRetryResponse` (around line 410):

```python
class DbReplicaHealthResponse(BaseModel):
    """Embedded Replica 健康快照 — 连接状态 + 同步性能 + 数据一致性。"""
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

- [ ] **Step 2: Verify syntax**

Run: `python -m py_compile web/backend/schemas.py`

- [ ] **Step 3: Commit**

```bash
git add web/backend/schemas.py
git commit -m "feat(api): add DbReplicaHealthResponse schema"
```

---

### Task 2: Backend — Add `/api/db/replica-health` endpoint

**Files:**
- Modify: `web/backend/routers/ops.py`

- [ ] **Step 1: Add the endpoint**

Add at the end of `ops.py`:

```python
@router.get("/db/replica-health", response_model=ApiResponse[DbReplicaHealthResponse])
async def db_replica_health(
    profile: Optional[str] = Query(default=None),
):
    """Embedded Replica 健康快照：连接 + 同步性能 + 数据一致性。"""
    import os
    from core.metrics import get_metrics_collector
    from database.execution_engine import get_db_sync_status, _write_queue_stats
    from web.backend.schemas import DbReplicaHealthResponse

    prof = _normalize_profile(profile)

    # 连接健康
    from database.connection import _main_write_conn_singleton, _main_write_conn_singleton_path
    conn_alive = _main_write_conn_singleton is not None
    is_cloud = bool(os.getenv("TURSO_DB_URL"))
    db_path = _main_write_conn_singleton_path or ""
    sync_status = get_db_sync_status()

    # 同步性能（从 MetricsCollector 取）
    coll = get_metrics_collector()
    sync_p50 = coll.percentile(prof, "db.idle_sync.duration_ms", 50)
    sync_p95 = coll.percentile(prof, "db.idle_sync.duration_ms", 95)
    sync_p99 = coll.percentile(prof, "db.idle_sync.duration_ms", 99)
    sync_count = coll.count(prof, "db.idle_sync.duration_ms")

    # 写队列统计
    wq = _write_queue_stats

    # 数据一致性
    schema_version = 0
    db_size_mb = 0.0
    try:
        import config as _cfg
        from database.connection import _get_read_conn, _get_singleton_conn_op_lock, _is_main_write_singleton_conn
        rconn = _get_read_conn(_cfg.DB_PATH)
        rlock = _get_singleton_conn_op_lock(rconn)
        rcur = rconn.cursor()
        try:
            if rlock is not None:
                with rlock:
                    rcur.execute("PRAGMA user_version")
                    row = rcur.fetchone()
                    schema_version = int(row[0]) if row else 0
            else:
                rcur.execute("PRAGMA user_version")
                row = rcur.fetchone()
                schema_version = int(row[0]) if row else 0
        finally:
            rcur.close()
        if not _is_main_write_singleton_conn(rconn):
            rconn.close()
        # 文件大小
        if os.path.exists(_cfg.DB_PATH):
            db_size_mb = round(os.path.getsize(_cfg.DB_PATH) / (1024 * 1024), 2)
    except Exception:
        pass

    return ok_response(DbReplicaHealthResponse(
        connection_alive=conn_alive,
        is_cloud=is_cloud,
        db_path=db_path,
        sync_in_progress=sync_status.get("syncing", False),
        last_sync_phase=sync_status.get("phase", ""),
        sync_p50_ms=sync_p50,
        sync_p95_ms=sync_p95,
        sync_p99_ms=sync_p99,
        sync_count=sync_count,
        write_queue_depth=wq.get("total_queued", 0) - wq.get("total_written", 0),
        write_total_queued=wq.get("total_queued", 0),
        write_total_written=wq.get("total_written", 0),
        write_total_errors=wq.get("total_errors", 0),
        schema_version=schema_version,
        db_size_mb=db_size_mb,
    ).model_dump(), user_id=prof)
```

- [ ] **Step 2: Add import for DbReplicaHealthResponse**

At the top of `ops.py`, add to the import from `web.backend.schemas`:

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

- [ ] **Step 3: Verify syntax**

Run: `python -m py_compile web/backend/routers/ops.py`

- [ ] **Step 4: Commit**

```bash
git add web/backend/routers/ops.py
git commit -m "feat(api): add /api/db/replica-health endpoint"
```

---

### Task 3: Frontend — Add TypeScript type + query key

**Files:**
- Modify: `web/frontend/src/api/types.ts`
- Modify: `web/frontend/src/queries/queryClient.ts`

- [ ] **Step 1: Add TS type**

Add at the end of `types.ts`:

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

- [ ] **Step 2: Add query key**

In `queryClient.ts`, add to `queryKeys`:

```typescript
dbReplicaHealth: (profile: string = activeProfile()) =>
  ['db_replica_health', profile] as const,
```

- [ ] **Step 3: Commit**

```bash
git add web/frontend/src/api/types.ts web/frontend/src/queries/queryClient.ts
git commit -m "feat(web): add DbReplicaHealth TS type and query key"
```

---

### Task 4: Frontend — Create `DbReplicaCard` component

**Files:**
- Create: `web/frontend/src/components/ops/DbReplicaCard.tsx`

- [ ] **Step 1: Create the component**

```tsx
/**
 * components/ops/DbReplicaCard.tsx — Embedded Replica 健康卡片。
 *
 * 展示：连接状态、同步性能 p50/p95、写队列、schema 版本、DB 大小。
 */
import { useQuery } from '@tanstack/react-query'
import {
  Database, Wifi, WifiOff, Loader2, HardDrive,
  Clock, AlertTriangle, CheckCircle2, Activity,
} from 'lucide-react'
import { apiClient } from '../../api/client'
import { queryKeys } from '../../queries/queryClient'
import type { DbReplicaHealthResponse } from '../../api/types'

function StatRow({ label, value, color = 'text-gray-700' }: {
  label: string; value: string | number; color?: string
}) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-xs text-gray-500">{label}</span>
      <span className={`text-sm font-medium ${color}`}>{value}</span>
    </div>
  )
}

function formatMs(ms: number | null): string {
  if (ms === null || ms === undefined) return '-'
  if (ms < 1) return `${(ms * 1000).toFixed(0)}us`
  if (ms < 1000) return `${ms.toFixed(1)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export default function DbReplicaCard({ profile }: { profile: string }) {
  const { data, error, isFetching } = useQuery({
    queryKey: queryKeys.dbReplicaHealth(profile),
    queryFn: async () => {
      const res = await apiClient<DbReplicaHealthResponse>(
        `/api/ops/db/replica-health?profile=${encodeURIComponent(profile)}`
      )
      return res.data
    },
    enabled: !!profile,
    refetchInterval: 15000,
    refetchIntervalInBackground: false,
  })

  if (error) {
    return (
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex items-center gap-2 mb-3">
          <Database size={16} />
          <h3 className="font-medium text-sm">DB 副本健康</h3>
        </div>
        <div className="text-red-500 text-sm">加载失败: {String(error)}</div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex items-center gap-2 mb-3">
          <Database size={16} />
          <h3 className="font-medium text-sm">DB 副本健康</h3>
        </div>
        <div className="flex items-center justify-center py-6">
          <Loader2 size={16} className="animate-spin text-gray-400" />
        </div>
      </div>
    )
  }

  const connOk = data.connection_alive
  const syncOk = !data.sync_in_progress

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Database size={16} />
          <h3 className="font-medium text-sm">DB 副本健康</h3>
        </div>
        <div className="flex items-center gap-1.5">
          {isFetching && <Loader2 size={12} className="animate-spin text-gray-400" />}
          {connOk ? (
            <span className="flex items-center gap-1 text-xs text-green-600">
              <Wifi size={12} /> 已连接
            </span>
          ) : (
            <span className="flex items-center gap-1 text-xs text-red-600">
              <WifiOff size={12} /> 断开
            </span>
          )}
        </div>
      </div>

      {/* 连接状态 */}
      <div className="mb-3">
        <div className="flex items-center gap-1.5 mb-1">
          {data.is_cloud ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-700">云端</span>
          ) : (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">本地</span>
          )}
          {data.sync_in_progress && (
            <span className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-yellow-100 text-yellow-700">
              <Loader2 size={10} className="animate-spin" />
              同步中{data.last_sync_phase ? `: ${data.last_sync_phase}` : ''}
            </span>
          )}
        </div>
        <div className="text-[11px] text-gray-400 truncate" title={data.db_path}>
          {data.db_path || '-'}
        </div>
      </div>

      {/* 同步性能 */}
      <div className="border-t pt-2 mb-2">
        <div className="text-[11px] text-gray-500 font-medium mb-1 flex items-center gap-1">
          <Clock size={10} /> 同步延迟 (5min)
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div className="text-center">
            <div className="text-sm font-bold text-gray-700">{formatMs(data.sync_p50_ms)}</div>
            <div className="text-[10px] text-gray-400">P50</div>
          </div>
          <div className="text-center">
            <div className={`text-sm font-bold ${(data.sync_p95_ms ?? 0) > 500 ? 'text-orange-500' : 'text-gray-700'}`}>
              {formatMs(data.sync_p95_ms)}
            </div>
            <div className="text-[10px] text-gray-400">P95</div>
          </div>
          <div className="text-center">
            <div className="text-sm font-bold text-gray-700">{data.sync_count}</div>
            <div className="text-[10px] text-gray-400">次数</div>
          </div>
        </div>
      </div>

      {/* 写队列 */}
      <div className="border-t pt-2 mb-2">
        <div className="text-[11px] text-gray-500 font-medium mb-1 flex items-center gap-1">
          <Activity size={10} /> 写队列
        </div>
        <StatRow label="积压" value={data.write_queue_depth} color={data.write_queue_depth > 100 ? 'text-orange-500' : 'text-gray-700'} />
        <StatRow label="累计写入" value={data.write_total_written} />
        <StatRow label="错误" value={data.write_total_errors} color={data.write_total_errors > 0 ? 'text-red-500' : 'text-gray-700'} />
      </div>

      {/* 数据一致性 */}
      <div className="border-t pt-2">
        <div className="text-[11px] text-gray-500 font-medium mb-1 flex items-center gap-1">
          <HardDrive size={10} /> 数据库
        </div>
        <StatRow label="Schema v" value={data.schema_version} />
        <StatRow label="文件大小" value={`${data.db_size_mb} MB`} />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify syntax**

Run: `cd web/frontend && npx tsc --noEmit --pretty 2>&1 | head -20`

- [ ] **Step 3: Commit**

```bash
git add web/frontend/src/components/ops/DbReplicaCard.tsx
git commit -m "feat(web): add DbReplicaCard component for OpsMonitor"
```

---

### Task 5: Frontend — Integrate DbReplicaCard into OpsMonitor

**Files:**
- Modify: `web/frontend/src/pages/OpsMonitor.tsx`

- [ ] **Step 1: Add import**

Add at the top of OpsMonitor.tsx:

```typescript
import DbReplicaCard from '../components/ops/DbReplicaCard'
```

- [ ] **Step 2: Add the 5th card**

In the grid section (after the "队列与延迟" card, around line 323), add:

```tsx
{/* 卡片5：DB 副本健康 */}
<DbReplicaCard profile={activeProfile ?? ''} />
```

- [ ] **Step 3: Update grid to 3 columns on large screens**

Change the grid container from `grid-cols-1 md:grid-cols-2` to `grid-cols-1 md:grid-cols-2 xl:grid-cols-3` to accommodate the 5th card better.

- [ ] **Step 4: Commit**

```bash
git add web/frontend/src/pages/OpsMonitor.tsx
git commit -m "feat(web): add DB replica health card to OpsMonitor"
```

---

### Task 6: Frontend — Add health banner to SyncStatus page

**Files:**
- Modify: `web/frontend/src/pages/SyncStatus.tsx`

- [ ] **Step 1: Add import and query**

Add imports:

```typescript
import { Wifi, WifiOff, Database, Loader2 as Loader2Icon, Clock } from 'lucide-react'
import type { DbReplicaHealthResponse } from '../api/types'
```

Add query inside the component (after the existing `useQuery`):

```typescript
const { data: replicaHealth } = useQuery({
  queryKey: queryKeys.dbReplicaHealth(),
  queryFn: async () => {
    const r = await apiClient<DbReplicaHealthResponse>('/api/ops/db/replica-health')
    return r.data
  },
  refetchInterval: 15000,
})
```

- [ ] **Step 2: Add health banner**

After the `<DegradedBanner />` and before `{retryResult && ...}`, add:

```tsx
{/* DB 副本健康状态条 */}
{replicaHealth && (
  <div className={`flex items-center gap-4 px-4 py-2.5 rounded-lg mb-4 text-sm ${
    replicaHealth.connection_alive ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'
  }`}>
    <div className="flex items-center gap-1.5">
      {replicaHealth.connection_alive ? (
        <Wifi size={14} className="text-green-600" />
      ) : (
        <WifiOff size={14} className="text-red-600" />
      )}
      <span className={replicaHealth.connection_alive ? 'text-green-700' : 'text-red-700'}>
        {replicaHealth.connection_alive ? 'DB 已连接' : 'DB 断开'}
      </span>
    </div>
    <span className="text-gray-400">|</span>
    <div className="flex items-center gap-1.5">
      <Database size={14} className="text-gray-500" />
      <span className="text-gray-600">
        {replicaHealth.is_cloud ? '云端' : '本地'} · Schema v{replicaHealth.schema_version} · {replicaHealth.db_size_mb}MB
      </span>
    </div>
    <span className="text-gray-400">|</span>
    <div className="flex items-center gap-1.5">
      <Clock size={14} className="text-gray-500" />
      <span className="text-gray-600">
        Sync P50: {replicaHealth.sync_p50_ms !== null ? `${replicaHealth.sync_p50_ms.toFixed(1)}ms` : '-'} ·
        P95: {replicaHealth.sync_p95_ms !== null ? `${replicaHealth.sync_p95_ms.toFixed(1)}ms` : '-'} ·
        {replicaHealth.sync_count} 次
      </span>
    </div>
    {replicaHealth.sync_in_progress && (
      <span className="flex items-center gap-1 text-yellow-600 ml-auto">
        <Loader2Icon size={12} className="animate-spin" />
        同步中
      </span>
    )}
  </div>
)}
```

- [ ] **Step 3: Commit**

```bash
git add web/frontend/src/pages/SyncStatus.tsx
git commit -m "feat(web): add DB replica health banner to SyncStatus page"
```

---

### Task 7: Verify end-to-end

- [ ] **Step 1: Syntax check backend**

```bash
python -m py_compile web/backend/schemas.py
python -m py_compile web/backend/routers/ops.py
```

- [ ] **Step 2: Syntax check frontend**

```bash
cd web/frontend && npx tsc --noEmit --pretty
```

- [ ] **Step 3: Start dev server and verify**

```bash
python scripts/start_web.py --dev
```

- [ ] **Step 4: Verify OpsMonitor shows 5th card**

Navigate to `/` (OpsMonitor), confirm "DB 副本健康" card appears with connection status, sync latency, write queue, and schema info.

- [ ] **Step 5: Verify SyncStatus shows health banner**

Navigate to `/sync`, confirm green/red banner appears at top showing connection status, cloud/local mode, schema version, sync p50/p95.

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat(web): DB replica health indicators — OpsMonitor card + SyncStatus banner"
```
