import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle, Loader2, RotateCcw } from 'lucide-react'
import { apiClient, apiPost } from '../api/client'
import { queryKeys } from '../queries/queryClient'
import type { SyncStatusResponse } from '../api/types'
import ErrorBanner from '../components/ui/ErrorBanner'

export default function TodayConflicts() {
  const queryClient = useQueryClient()

  const { data, error, isFetching, refetch } = useQuery({
    queryKey: queryKeys.syncStatus(),
    queryFn: async () => {
      const r = await apiClient<SyncStatusResponse>('/api/sync/status')
      return r.data
    },
  })

  const retryMutation = useMutation({
    mutationFn: () => apiPost<{ retried: number; total_conflicts: number; message?: string }>('/api/sync/retry'),
    onSuccess: () => {
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ['sync_status'] }), 1200)
    },
  })

  const conflicts = data?.conflicts ?? []

  const errorMsg = (
    error || retryMutation.error
      ? String((error ?? retryMutation.error) instanceof Error ? (error ?? retryMutation.error as Error).message : (error ?? retryMutation.error))
      : ''
  )

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold text-text-primary">今日冲突</h2>
          <p className="text-sm text-text-muted">仅展示 sync_status=2 的单词，不计入今日待处理</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="px-3 py-1.5 border border-border-default rounded-button text-sm text-text-secondary hover:bg-surface-hover transition-colors disabled:opacity-50"
          >
            刷新
          </button>
          <button
            onClick={() => retryMutation.mutate()}
            disabled={retryMutation.isPending || conflicts.length === 0}
            className="flex items-center gap-1 px-3 py-1.5 bg-warning text-white rounded-button text-sm hover:bg-warning/90 disabled:opacity-50 transition-colors"
          >
            {retryMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
            复查云端状态
          </button>
          <Link
            to="/today"
            className="px-3 py-1.5 border border-border-default rounded-button text-sm text-text-secondary hover:bg-surface-hover transition-colors"
          >
            返回今日任务
          </Link>
        </div>
      </div>

      <ErrorBanner message={errorMsg} />

      {conflicts.length > 0 ? (
        <div className="bg-surface-card rounded-card border border-border-default shadow-card overflow-hidden">
          <div className="px-4 py-2 bg-error-soft text-error text-sm font-medium border-b border-border-soft flex items-center gap-2">
            <AlertTriangle size={14} />
            冲突记录（sync_status=2）
          </div>
          <table className="w-full text-sm">
            <thead className="bg-surface-hover">
              <tr>
                <th className="text-left px-4 py-2 font-medium text-text-secondary">单词</th>
                <th className="text-left px-4 py-2 font-medium text-text-secondary">释义</th>
                <th className="text-left px-4 py-2 font-medium text-text-secondary">匹配度</th>
                <th className="text-left px-4 py-2 font-medium text-text-secondary">冲突原因</th>
              </tr>
            </thead>
            <tbody>
              {conflicts.map((c: any) => (
                <tr key={c.voc_id} className="border-t border-border-soft hover:bg-surface-hover transition-colors">
                  <td className="px-4 py-2 font-medium text-text-primary">{c.spelling}</td>
                  <td className="px-4 py-2 text-text-secondary max-w-xs truncate">{c.basic_meanings || '—'}</td>
                  <td className="px-4 py-2 text-text-secondary">
                    {c.match_confidence !== null && c.match_confidence !== undefined ? `${(c.match_confidence * 100).toFixed(1)}%` : '—'}
                  </td>
                  <td className="px-4 py-2 text-text-secondary text-xs">{c.match_reason || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-center py-12 text-text-muted">当前没有冲突项</div>
      )}
    </div>
  )
}