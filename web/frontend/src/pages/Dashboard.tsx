/**
 * pages/Dashboard.tsx — 仪表盘：展示核心统计卡片。
 *
 * React Query 改造（PLAYBOOK B4）：
 * - stats summary / session 各走一份 useQuery，去掉手写 useState/useEffect/load
 * - 切换 profile 走 useOnActiveUserChanged → invalidateQueries（与其他 RQ 页面统一）
 * - 加载时显示 6 个骨架卡片而不是 "加载中..." 文字
 * - StatsSummary 带 `degraded: true` 时挂 DegradedBanner（PLAYBOOK A4 通道）
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { useOnActiveUserChanged } from '../hooks/useOnActiveUserChanged'
import { queryKeys } from '../queries/queryClient'
import ErrorBanner from '../components/ui/ErrorBanner'
import DegradedBanner from '../components/ui/DegradedBanner'
import { SkeletonCard } from '../components/ui/Skeleton'
import type { StatsSummary, SessionInfo } from '../api/types'
import { BookOpen, Brain, Zap, AlertTriangle, Database, Clock } from 'lucide-react'

export default function Dashboard() {
  const queryClient = useQueryClient()

  const { data: stats, error: statsError } = useQuery({
    queryKey: queryKeys.statsSummary(),
    queryFn: async () => {
      const r = await apiClient<StatsSummary>('/api/stats/summary')
      return r.data
    },
  })

  const { data: session } = useQuery({
    queryKey: queryKeys.session(),
    queryFn: async () => {
      const r = await apiClient<SessionInfo>('/api/session')
      return r.data
    },
  })

  useOnActiveUserChanged(() => {
    queryClient.invalidateQueries({ queryKey: ['stats_summary'] })
    queryClient.invalidateQueries({ queryKey: ['session'] })
  })

  const errorMsg = statsError ? String(statsError instanceof Error ? statsError.message : statsError) : ''

  const cards = stats ? [
    { label: '总单词数', value: stats.total_words, icon: BookOpen, color: 'bg-blue-500' },
    { label: '已处理', value: stats.processed_words, icon: Zap, color: 'bg-green-500' },
    { label: 'AI 笔记', value: stats.ai_notes_count, icon: Brain, color: 'bg-purple-500' },
    { label: '薄弱词', value: stats.weak_words_count, icon: AlertTriangle, color: 'bg-red-500' },
    { label: '同步队列', value: stats.sync_queue_depth, icon: Database, color: 'bg-yellow-500' },
    { label: '平均耗时', value: `${stats.avg_latency_ms}ms`, icon: Clock, color: 'bg-gray-500' },
  ] : []

  return (
    <div className="p-6">
      <h2 className="text-2xl font-bold mb-1">仪表盘</h2>
      <p className="text-gray-500 mb-6">
        {session ? `Profile: ${session.active_profile}` : '加载中...'}
      </p>

      <ErrorBanner message={errorMsg} size="base" />
      <DegradedBanner
        active={stats?.degraded}
        message="统计数据已降级展示"
        reason={stats?.degraded_reason}
      />

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {stats ? (
          cards.map(c => (
            <div key={c.label} className="bg-white rounded-lg shadow p-4 flex items-center gap-4">
              <div className={`${c.color} p-3 rounded-lg text-white`}>
                <c.icon size={20} />
              </div>
              <div>
                <div className="text-2xl font-bold">{c.value}</div>
                <div className="text-sm text-gray-500">{c.label}</div>
              </div>
            </div>
          ))
        ) : (
          Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)
        )}
      </div>

      {stats && (
        <div className="mt-6 bg-white rounded-lg shadow p-4">
          <h3 className="font-medium mb-2">AI 调用统计</h3>
          <div className="grid grid-cols-3 gap-4 text-sm">
            <div><span className="text-gray-500">总批次：</span>{stats.ai_batches}</div>
            <div><span className="text-gray-500">总 Tokens：</span>{(stats.total_tokens ?? 0).toLocaleString()}</div>
            <div><span className="text-gray-500">平均延迟：</span>{stats.avg_latency_ms}ms</div>
          </div>
        </div>
      )}
    </div>
  )
}
