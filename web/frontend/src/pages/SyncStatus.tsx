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
import type { SyncStatusResponse } from '../api/types'
import { RefreshCcw, Loader2, AlertTriangle, RotateCcw } from 'lucide-react'

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
        setRetryResult(`已重试 ${res.data.retried} / ${res.data.total_conflicts} 项`)
      }
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ['sync_status'] }), 1500)
    },
    onError: () => setRetryResult(''),
  })

  const queueDepth = data?.queue_depth ?? 0
  const conflictCount = data?.conflict_count ?? 0
  const conflicts = data?.conflicts ?? []

  // 错误展示：query / 任一 mutation 出错都显示
  const errorMsg = (
    error || flushMutation.error || retryMutation.error
      ? String((error ?? flushMutation.error ?? retryMutation.error) instanceof Error
          ? (error ?? flushMutation.error ?? retryMutation.error as Error).message
          : (error ?? flushMutation.error ?? retryMutation.error))
      : ''
  )

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold">同步状态</h2>
          <p className="text-gray-500">{data ? `队列深度: ${queueDepth} · 冲突: ${conflictCount}` : '加载中...'}</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => refetch()} className="px-3 py-1.5 border rounded text-sm hover:bg-gray-50">刷新</button>
          {data && conflictCount > 0 && (
            <button onClick={() => retryMutation.mutate()} disabled={retryMutation.isPending}
              className="flex items-center gap-1 px-3 py-1.5 bg-orange-500 text-white rounded text-sm hover:bg-orange-600 disabled:opacity-50">
              {retryMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
              重试冲突
            </button>
          )}
          <button onClick={() => flushMutation.mutate()} disabled={flushMutation.isPending}
            className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50">
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
      {retryResult && <div className="bg-green-50 text-green-700 p-3 rounded mb-4 text-sm">✅ {retryResult}</div>}

      {data && conflicts.length > 0 && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <div className="px-4 py-2 bg-red-50 text-red-700 text-sm font-medium border-b flex items-center gap-2">
            <AlertTriangle size={14} />
            冲突记录（sync_status=2）
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50"><tr>
              <th className="text-left px-4 py-2 font-medium text-gray-600">单词</th>
              <th className="text-left px-4 py-2 font-medium text-gray-600">释义</th>
              <th className="text-left px-4 py-2 font-medium text-gray-600">创建时间</th>
            </tr></thead>
            <tbody>{conflicts.map(c => (
              <tr key={c.voc_id} className="border-t hover:bg-gray-50">
                <td className="px-4 py-2 font-medium">{c.spelling}</td>
                <td className="px-4 py-2 text-gray-600 max-w-xs truncate">{c.basic_meanings || '—'}</td>
                <td className="px-4 py-2 text-gray-400 text-xs">{c.created_at}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}

      {data && queueDepth > 0 && conflicts.length === 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-blue-700 text-sm">
          📤 有 {queueDepth} 条待同步记录正在处理中...
        </div>
      )}

      {data && conflicts.length === 0 && queueDepth === 0 && (
        <div className="text-center py-12 text-gray-400">✅ 无冲突记录，同步队列为空</div>
      )}
    </div>
  )
}
