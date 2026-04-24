/**
 * pages/FuturePlan.tsx — 未来计划：选择天数预览 + 触发处理。
 */
import { useCallback, useEffect, useState } from 'react'
import { apiClient, apiPost } from '../api/client'
import { useOnActiveUserChanged } from '../hooks/useOnActiveUserChanged'
import { useTaskStore } from '../stores/tasks'
import type { FutureItemsResponse, TaskSubmitResponse } from '../api/types'
import { PlayCircle, Loader2, Search } from 'lucide-react'

export default function FuturePlan() {
  const [days, setDays] = useState(7)
  const [data, setData] = useState<FutureItemsResponse | null>(null)
  const [error, setError] = useState('')
  const [processing, setProcessing] = useState(false)
  const setActiveTask = useTaskStore(s => s.setActiveTask)
  const items = data?.items ?? []

  const load = useCallback(() => {
    setError('')
    apiClient<FutureItemsResponse>(`/api/study/future?days=${days}`)
      .then(r => setData(r.data))
      .catch(e => setError(String(e)))
  }, [days])

  useEffect(() => { load() }, [load])
  useOnActiveUserChanged(load)

  const handleProcess = async () => {
    if (!data?.items?.length) return
    setProcessing(true)
    try {
      const res = await apiPost<TaskSubmitResponse>(`/api/study/process-future?days=${days}`)
      if (res.data?.task_id) setActiveTask(res.data.task_id)
    } catch (e) { setError(String(e)) }
    finally { setProcessing(false) }
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold">未来计划</h2>
          <p className="text-gray-500">{data ? `${data.count} 个单词（未来 ${days} 天）` : '加载中...'}</p>
        </div>
        <div className="flex items-center gap-3">
          <select value={days} onChange={e => setDays(Number(e.target.value))} className="border rounded px-2 py-1 text-sm">
            {[3, 5, 7, 14, 21, 30].map(d => <option key={d} value={d}>{d} 天</option>)}
          </select>
          <button onClick={load} className="p-2 border rounded hover:bg-gray-50"><Search size={16} /></button>
          <button onClick={handleProcess} disabled={processing || !data?.count}
            className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors">
            {processing ? <Loader2 size={16} className="animate-spin" /> : <PlayCircle size={16} />}
            全部处理
          </button>
        </div>
      </div>

      {error && <div className="bg-red-50 text-red-700 p-3 rounded mb-4">{error}</div>}

      {data && items.length > 0 && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50"><tr>
              <th className="text-left px-4 py-2 font-medium text-gray-600">#</th>
              <th className="text-left px-4 py-2 font-medium text-gray-600">单词</th>
              <th className="text-left px-4 py-2 font-medium text-gray-600">释义</th>
            </tr></thead>
            <tbody>{items.map((item, i) => (
              <tr key={item.voc_id} className="border-t hover:bg-gray-50">
                <td className="px-4 py-2 text-gray-400">{i + 1}</td>
                <td className="px-4 py-2 font-medium">{item.voc_spelling}</td>
                <td className="px-4 py-2 text-gray-600">{item.voc_meanings || '—'}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {data && items.length === 0 && <div className="text-center py-12 text-gray-400">未来 {days} 天无待处理单词</div>}
    </div>
  )
}
