/**
 * pages/Iteration.tsx — 智能迭代：候选列表 + 触发迭代 + 行级进度。
 */
import { useCallback, useEffect, useState } from 'react'
import { apiClient, apiPost } from '../api/client'
import { useTaskStore } from '../stores/tasks'
import type { IterationCandidatesResponse, TaskSubmitResponse } from '../api/types'
import { RefreshCw, Loader2 } from 'lucide-react'
import { buildRowStatusMap, rowDisplayLabel, rowPhaseLabel } from '../utils/rowProgress'
import { useOnActiveUserChanged } from '../hooks/useOnActiveUserChanged'

export default function Iteration() {
  const [processing, setProcessing] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [data, setData] = useState<IterationCandidatesResponse | null>(null)
  const setActiveTask = useTaskStore((s) => s.setActiveTask)
  const events = useTaskStore((s) => s.events)
  const taskStatus = useTaskStore((s) => s.taskStatus)

  const items = data?.items ?? []
  const rowStatusMap = buildRowStatusMap(items, events, taskStatus)

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    apiClient<IterationCandidatesResponse>('/api/study/iterate-candidates?limit=100')
      .then((res) => setData(res.data))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])
  useOnActiveUserChanged(load)

  const handleIterate = async () => {
    setProcessing(true)
    setError('')
    try {
      const res = await apiPost<TaskSubmitResponse>('/api/study/iterate')
      if (res.data?.task_id) setActiveTask(res.data.task_id)
    } catch (e) {
      setError(String(e))
    } finally {
      setProcessing(false)
    }
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold mb-1">智能迭代</h2>
          <p className="text-gray-500">{data ? `${data.count || 0} 个候选薄弱词` : '加载中...'}</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={load} className="px-3 py-2 border rounded-lg text-sm hover:bg-gray-50">刷新候选</button>
          <button
            onClick={handleIterate}
            disabled={processing}
            className="flex items-center gap-2 bg-purple-600 text-white px-4 py-2 rounded-lg hover:bg-purple-700 disabled:opacity-50 transition-colors"
          >
            {processing ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
            启动智能迭代
          </button>
        </div>
      </div>

      {error && <div className="bg-red-50 text-red-700 p-3 rounded mb-4">{error}</div>}
      {loading && <div className="text-gray-400">加载中...</div>}

      {!loading && items.length > 0 && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-4 py-2 font-medium text-gray-600">#</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">单词</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">释义</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">Level</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">弱词分</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">进度</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, i) => {
                const key = item.voc_spelling.toLowerCase()
                const state = rowStatusMap[key]
                return (
                  <tr key={item.voc_id} className="border-t hover:bg-gray-50">
                    <td className="px-4 py-2 text-gray-400">{i + 1}</td>
                    <td className="px-4 py-2 font-medium">{item.voc_spelling}</td>
                    <td className="px-4 py-2 text-gray-600">{item.voc_meanings || '—'}</td>
                    <td className="px-4 py-2 text-gray-600">{item.it_level ?? 0}</td>
                    <td className="px-4 py-2 text-gray-600">{(item.weak_score ?? 0).toFixed(1)}</td>
                    <td className="px-4 py-2">
                      <span
                        className="text-xs px-2 py-1 rounded bg-gray-100 text-gray-700"
                        title={[
                          rowPhaseLabel(state?.phase),
                          state?.reason || '',
                        ].filter(Boolean).join(' | ')}
                      >
                        {rowDisplayLabel(state)}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {!loading && items.length === 0 && (
        <div className="text-center py-12 text-gray-400">当前没有可迭代候选词</div>
      )}
    </div>
  )
}

