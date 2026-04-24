/**
 * pages/Dashboard.tsx — 仪表盘：展示核心统计卡片。
 */
import { useEffect, useState } from 'react'
import { apiClient } from '../api/client'
import type { StatsSummary, SessionInfo } from '../api/types'
import { BookOpen, Brain, Zap, AlertTriangle, Database, Clock } from 'lucide-react'

export default function Dashboard() {
  const [stats, setStats] = useState<StatsSummary | null>(null)
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    apiClient<StatsSummary>('/api/stats/summary')
      .then(r => setStats(r.data))
      .catch(e => setError(String(e)))
    apiClient<SessionInfo>('/api/session')
      .then(r => setSession(r.data))
      .catch(() => {})
  }, [])

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
        {session ? `用户: ${session.active_user} · AI: ${session.ai_provider}` : '加载中...'}
      </p>

      {error && <div className="bg-red-50 text-red-700 p-3 rounded mb-4">{error}</div>}

      {!stats && !error && <div className="text-gray-400 py-12 text-center">加载统计数据中...</div>}

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {cards.map(c => (
          <div key={c.label} className="bg-white rounded-lg shadow p-4 flex items-center gap-4">
            <div className={`${c.color} p-3 rounded-lg text-white`}>
              <c.icon size={20} />
            </div>
            <div>
              <div className="text-2xl font-bold">{c.value}</div>
              <div className="text-sm text-gray-500">{c.label}</div>
            </div>
          </div>
        ))}
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
