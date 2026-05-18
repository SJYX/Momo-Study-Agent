/**
 * components/ops/DbReplicaCard.tsx — Embedded Replica 健康卡片。
 *
 * 展示：连接状态、同步性能 p50/p95、写队列、schema 版本、DB 大小。
 */
import { useQuery } from '@tanstack/react-query'
import {
  Database, Wifi, WifiOff, Loader2,
  Clock, HardDrive, Activity,
} from 'lucide-react'
import { apiClient } from '../../api/client'
import { queryKeys } from '../../queries/queryClient'
import type { DbReplicaHealthResponse } from '../../api/types'

function StatRow({ label, value, color = 'text-text-primary' }: {
  label: string; value: string | number; color?: string
}) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-xs text-text-muted">{label}</span>
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
        `/api/ops/db/replica-health?profile=${encodeURIComponent(profile)}`,
      )
      return res.data
    },
    enabled: !!profile,
    refetchInterval: 15000,
    refetchIntervalInBackground: false,
  })

  if (error) {
    return (
      <div className="bg-surface-card rounded-card border border-border-default shadow-card p-4">
        <div className="flex items-center gap-2 mb-3">
          <Database size={16} />
          <h3 className="font-medium text-sm text-text-primary">DB 副本健康</h3>
        </div>
        <div className="text-error text-sm">加载失败: {String(error)}</div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="bg-surface-card rounded-card border border-border-default shadow-card p-4">
        <div className="flex items-center gap-2 mb-3">
          <Database size={16} />
          <h3 className="font-medium text-sm text-text-primary">DB 副本健康</h3>
        </div>
        <div className="flex items-center justify-center py-6">
          <Loader2 size={16} className="animate-spin text-text-muted" />
        </div>
      </div>
    )
  }

  const connOk = data.connection_alive

  return (
    <div className="bg-surface-card rounded-card border border-border-default shadow-card p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Database size={16} className="text-text-secondary" />
          <h3 className="text-base font-medium text-text-primary">DB 副本健康</h3>
        </div>
        <div className="flex items-center gap-1.5">
          {isFetching && <Loader2 size={12} className="animate-spin text-text-muted" />}
          {connOk ? (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-pill text-xs font-medium bg-success-soft text-success">
              <Wifi size={12} /> 已连接
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-pill text-xs font-medium bg-error-soft text-error">
              <WifiOff size={12} /> 断开
            </span>
          )}
        </div>
      </div>

      {/* 连接状态 */}
      <div className="mb-3">
        <div className="flex items-center gap-1.5 mb-1">
          {data.is_cloud ? (
            <span className="inline-flex items-center px-2 py-0.5 rounded-pill text-xs font-medium bg-accent-soft text-accent">云端</span>
          ) : (
            <span className="inline-flex items-center px-2 py-0.5 rounded-pill text-xs font-medium bg-surface-hover text-text-secondary">本地</span>
          )}
          {data.sync_in_progress && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-pill text-xs font-medium bg-warning-soft text-warning">
              <Loader2 size={10} className="animate-spin" />
              同步中{data.last_sync_phase ? `: ${data.last_sync_phase}` : ''}
            </span>
          )}
        </div>
        <div className="text-xs text-text-muted truncate" title={data.db_path}>
          {data.db_path || '-'}
        </div>
      </div>

      {/* 同步性能 */}
      <div className="border-t border-border-soft pt-2 mb-2">
        <div className="text-xs text-text-secondary font-medium mb-1 flex items-center gap-1">
          <Clock size={10} /> 同步延迟 (5min)
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div className="text-center">
            <div className="text-sm font-bold text-text-primary">{formatMs(data.sync_p50_ms)}</div>
            <div className="text-[10px] text-text-muted">P50</div>
          </div>
          <div className="text-center">
            <div className={`text-sm font-bold ${(data.sync_p95_ms ?? 0) > 500 ? 'text-warning' : 'text-text-primary'}`}>
              {formatMs(data.sync_p95_ms)}
            </div>
            <div className="text-[10px] text-text-muted">P95</div>
          </div>
          <div className="text-center">
            <div className="text-sm font-bold text-text-primary">{data.sync_count}</div>
            <div className="text-[10px] text-text-muted">次数</div>
          </div>
        </div>
      </div>

      {/* 写队列 */}
      <div className="border-t border-border-soft pt-2 mb-2">
        <div className="text-xs text-text-secondary font-medium mb-1 flex items-center gap-1">
          <Activity size={10} /> 写队列
        </div>
        <StatRow label="积压" value={data.write_queue_depth} color={data.write_queue_depth > 100 ? 'text-warning' : 'text-text-primary'} />
        <StatRow label="累计写入" value={data.write_total_written} />
        <StatRow label="错误" value={data.write_total_errors} color={data.write_total_errors > 0 ? 'text-error' : 'text-text-primary'} />
      </div>

      {/* 数据一致性 */}
      <div className="border-t border-border-soft pt-2">
        <div className="text-xs text-text-secondary font-medium mb-1 flex items-center gap-1">
          <HardDrive size={10} /> 数据库
        </div>
        <StatRow label="Schema v" value={data.schema_version} />
        <StatRow label="文件大小" value={`${data.db_size_mb} MB`} />
      </div>
    </div>
  )
}
