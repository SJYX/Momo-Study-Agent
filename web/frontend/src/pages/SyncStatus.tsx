/**
 * pages/SyncStatus.tsx — 同步状态：队列深度 + 冲突列表 + 重试。
 *
 * React Query 改造：拉取改 useQuery；flush/retry 改 useMutation；mutation 终态 invalidate 重拉。
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient, apiPost } from '../api/client'
import { useOnActiveUserChanged } from '../hooks/useOnActiveUserChanged'
import { queryKeys } from '../queries/queryClient'
import ErrorBanner from '../components/ui/ErrorBanner'
import DegradedBanner from '../components/ui/DegradedBanner'
import type { SyncStatusResponse, DbReplicaHealthResponse } from '../api/types'
import { RefreshCcw, Loader2, AlertTriangle, RotateCcw, AlertOctagon, Wifi, WifiOff, Database, Clock } from 'lucide-react'

export default function SyncStatus() {
  const queryClient = useQueryClient()
  const [retryResult, setRetryResult] = useState('')

  const { data, error, refetch } = useQuery({
    queryKey: queryKeys.syncStatus(),
    queryFn: async () => {
      const r = await apiClient<SyncStatusResponse>('/api/sync/status')
      return r.data
    },
  })

  useOnActiveUserChanged(() => {
    queryClient.invalidateQueries({ queryKey: ['sync_status'] })
  })

  const { data: replicaHealth } = useQuery({
    queryKey: queryKeys.dbReplicaHealth(),
    queryFn: async () => {
      const r = await apiClient<DbReplicaHealthResponse>('/api/ops/db/replica-health')
      return r.data
    },
    refetchInterval: 15000,
  })

  const flushMutation = useMutation({
    mutationFn: () => apiPost('/api/sync/flush'),
    onSuccess: () => {
      // 后端写入后小延迟再重拉，让队列状态有时间更新
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ['sync_status'] }), 1000)
    },
  })

  const retryMutation = useMutation({
    mutationFn: () => apiPost<{ retried: number; total_conflicts: number; message?: string }>('/api/sync/retry'),
    onSuccess: (res) => {
      if (res.data) {
        setRetryResult(`已发起 ${res.data.retried} 次云端复查（云端未变化的词仍保留冲突状态，需先在墨墨 App 中删除冲突释义）`)
      }
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ['sync_status'] }), 1500)
    },
    onError: () => setRetryResult(''),
  })

  const retryFailedMutation = useMutation({
    mutationFn: () => apiPost<{ retried: number; total_failed: number; message?: string }>('/api/sync/retry_failed'),
    onSuccess: (res) => {
      if (res.data) {
        setRetryResult(`已发起 ${res.data.retried} 次失败重试`)
      }
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ['sync_status'] }), 1500)
    },
    onError: () => setRetryResult(''),
  })

  const queueDepth = data?.queue_depth ?? 0
  const conflictCount = data?.conflict_count ?? 0
  const conflicts = data?.conflicts ?? []
  const failedCount = data?.failed_count ?? 0
  const failedItems = data?.failed_items ?? []

  // 错误展示：query / 任一 mutation 出错都显示
  const errorMsg = (
    error || flushMutation.error || retryMutation.error || retryFailedMutation.error
      ? String((error ?? flushMutation.error ?? retryMutation.error ?? retryFailedMutation.error) instanceof Error
          ? (error ?? flushMutation.error ?? retryMutation.error ?? retryFailedMutation.error as Error).message
          : (error ?? flushMutation.error ?? retryMutation.error ?? retryFailedMutation.error))
      : ''
  )

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold text-text-primary">同步状态</h2>
          <p className="text-sm text-text-muted">{data ? `队列深度: ${queueDepth} · 冲突: ${conflictCount}` : '加载中...'}</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => refetch()} className="px-3 py-1.5 border border-border-default rounded-button text-sm text-text-secondary hover:bg-surface-hover transition-colors">刷新</button>
          {data && conflictCount > 0 && (
            <button
              onClick={() => retryMutation.mutate()}
              disabled={retryMutation.isPending}
              title="复查云端释义是否仍冲突。若云端未变,本地仍标记为冲突；真正解除需先在墨墨 App 中删除冲突释义,再次点击复查即可自动同步本地版本。"
              className="flex items-center gap-1 px-3 py-1.5 bg-warning text-white rounded-button text-sm hover:bg-warning/90 disabled:opacity-50 transition-colors">
              {retryMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
              复查云端状态
            </button>
          )}
          {data && failedCount > 0 && (
            <button
              onClick={() => retryFailedMutation.mutate()}
              disabled={retryFailedMutation.isPending}
              title="重试同步失败的记录"
              className="flex items-center gap-1 px-3 py-1.5 bg-error text-white rounded-button text-sm hover:bg-error/90 disabled:opacity-50 transition-colors">
              {retryFailedMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
              重试失败记录
            </button>
          )}
          <button onClick={() => flushMutation.mutate()} disabled={flushMutation.isPending}
            className="flex items-center gap-1 px-3 py-1.5 bg-accent text-white rounded-button text-sm hover:bg-accent-hover disabled:opacity-50 transition-colors">
            {flushMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <RefreshCcw size={14} />}
            立即同步
          </button>
        </div>
      </div>

      <ErrorBanner message={errorMsg} />
      <DegradedBanner
        active={data?.degraded}
        message="同步状态查询已降级（性能保护中）"
        reason={data?.degraded_reason}
      />

      {/* DB 副本健康状态条 */}
      {replicaHealth && (
        <div className={`flex flex-wrap items-center gap-4 px-4 py-2.5 rounded-card mb-4 text-sm border ${
          replicaHealth.connection_alive ? 'bg-success-soft border-success/20' : 'bg-error-soft border-error/20'
        }`}>
          <div className="flex items-center gap-1.5">
            {replicaHealth.connection_alive ? (
              <Wifi size={14} className="text-success" />
            ) : (
              <WifiOff size={14} className="text-error" />
            )}
            <span className={replicaHealth.connection_alive ? 'text-success font-medium' : 'text-error font-medium'}>
              {replicaHealth.connection_alive ? 'DB 已连接' : 'DB 断开'}
            </span>
          </div>
          <span className="text-border-default">|</span>
          <div className="flex items-center gap-1.5">
            <Database size={14} className="text-text-muted" />
            <span className="text-text-secondary">
              {replicaHealth.is_cloud ? '云端' : '本地'} · Schema v{replicaHealth.schema_version} · {replicaHealth.db_size_mb}MB
            </span>
          </div>
          <span className="text-border-default">|</span>
          <div className="flex items-center gap-1.5">
            <Clock size={14} className="text-text-muted" />
            <span className="text-text-secondary">
              Sync P50: {replicaHealth.sync_p50_ms !== null ? `${replicaHealth.sync_p50_ms.toFixed(1)}ms` : '-'} ·
              P95: {replicaHealth.sync_p95_ms !== null ? `${replicaHealth.sync_p95_ms.toFixed(1)}ms` : '-'} ·
              {replicaHealth.sync_count} 次
            </span>
          </div>
          {replicaHealth.sync_in_progress && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-pill text-xs font-medium bg-warning-soft text-warning ml-auto">
              <Loader2 size={12} className="animate-spin" />
              同步中
            </span>
          )}
        </div>
      )}
      {retryResult && <div className="bg-success-soft text-success p-3 rounded-card mb-4 text-sm border border-success/20">✅ {retryResult}</div>}

      {data && conflicts.length > 0 && (
        <div className="bg-surface-card rounded-card border border-border-default shadow-card overflow-hidden">
          <div className="px-4 py-2 bg-error-soft text-error text-sm font-medium border-b border-border-soft flex items-center gap-2">
            <AlertTriangle size={14} />
            冲突记录（sync_status=2）
          </div>
          <table className="w-full text-sm">
            <thead className="bg-surface-hover"><tr>
              <th className="text-left px-4 py-2 font-medium text-text-secondary">单词</th>
              <th className="text-left px-4 py-2 font-medium text-text-secondary">释义</th>
              <th className="text-left px-4 py-2 font-medium text-text-secondary">匹配度</th>
              <th className="text-left px-4 py-2 font-medium text-text-secondary">差异原因</th>
              <th className="text-left px-4 py-2 font-medium text-text-secondary">创建时间</th>
            </tr></thead>
            <tbody>{conflicts.map((c: any) => (
              <tr key={c.voc_id} className="border-t border-border-soft hover:bg-surface-hover transition-colors">
                <td className="px-4 py-2 font-medium text-text-primary">{c.spelling}</td>
                <td className="px-4 py-2 text-text-secondary max-w-xs truncate">{c.basic_meanings || '—'}</td>
                <td className="px-4 py-2 text-text-secondary">{c.match_confidence !== null && c.match_confidence !== undefined ? `${(c.match_confidence * 100).toFixed(1)}%` : '—'}</td>
                <td className="px-4 py-2 text-text-secondary text-xs">{c.match_reason || '—'}</td>
                <td className="px-4 py-2 text-text-muted text-xs">{c.created_at}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}

      {data && failedItems.length > 0 && (
        <div className="bg-surface-card rounded-card border border-border-default shadow-card overflow-hidden mt-4">
          <div className="px-4 py-2 bg-error-soft text-error text-sm font-medium border-b border-border-soft flex items-center gap-2">
            <AlertOctagon size={14} />
            失败记录（sync_status=5）
          </div>
          <table className="w-full text-sm">
            <thead className="bg-surface-hover"><tr>
              <th className="text-left px-4 py-2 font-medium text-text-secondary">单词</th>
              <th className="text-left px-4 py-2 font-medium text-text-secondary">释义</th>
              <th className="text-left px-4 py-2 font-medium text-text-secondary">创建时间</th>
            </tr></thead>
            <tbody>{failedItems.map((c: any) => (
              <tr key={c.voc_id} className="border-t border-border-soft hover:bg-surface-hover transition-colors">
                <td className="px-4 py-2 font-medium text-text-primary">{c.spelling}</td>
                <td className="px-4 py-2 text-text-secondary max-w-xs truncate">{c.basic_meanings || '—'}</td>
                <td className="px-4 py-2 text-text-muted text-xs">{c.created_at}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}

      {data && queueDepth > 0 && conflicts.length === 0 && failedItems.length === 0 && (
        <div className="bg-accent-soft border border-accent/20 rounded-card p-4 text-accent-hover text-sm mt-4">
          📤 有 {queueDepth} 条待同步记录正在处理中...
        </div>
      )}

      {data && conflicts.length === 0 && failedItems.length === 0 && queueDepth === 0 && (
        <div className="text-center py-12 text-text-muted mt-4">✅ 无冲突或失败记录，同步队列为空</div>
      )}
    </div>
  )
}
