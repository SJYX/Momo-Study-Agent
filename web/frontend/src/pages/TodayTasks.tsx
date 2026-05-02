/**
 * pages/TodayTasks.tsx — 今日任务列表 + 触发处理。
 *
 * V1-T1（flag: ff_today_default_view）：
 *   - 行视图保持（沿用现有表格）
 *   - 默认筛选"仅可执行项"（V1 近似：phase != 'skipped' && status != 'done'）
 *   - 价值优先 + 时间压力次级排序（V1 近似见 utils/todayView.ts）
 *   - 一键"查看全部"切换
 *   flag 关闭时回退到原始行为，列表不排序、不筛选。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiClient, apiPost } from '../api/client'
import { useOnActiveUserChanged } from '../hooks/useOnActiveUserChanged'
import { useTaskStore } from '../stores/tasks'
import type { TodayItemsResponse, TaskSubmitResponse } from '../api/types'
import { PlayCircle, Loader2, Filter } from 'lucide-react'
import { buildRowStatusMap, rowDisplayLabel, rowPhaseLabel } from '../utils/rowProgress'
import { isEnabled } from '../utils/featureFlags'
import { filterExecutable, sortByValue } from '../utils/todayView'

export default function TodayTasks() {
  const [data, setData] = useState<TodayItemsResponse | null>(null)
  const [error, setError] = useState('')
  const [processing, setProcessing] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const setActiveTask = useTaskStore(s => s.setActiveTask)
  const events = useTaskStore(s => s.events)
  const taskStatus = useTaskStore(s => s.taskStatus)
  const items = data?.items ?? []
  const rowStatusMap = buildRowStatusMap(items, events, taskStatus)

  // V1-T1：flag 开启时改造默认视图。flag 关闭时维持原始顺序与不筛选。
  const defaultViewEnabled = isEnabled('ff_today_default_view')
  const sortedItems = useMemo(
    () => (defaultViewEnabled ? sortByValue(items) : items),
    [defaultViewEnabled, items],
  )
  const executableItems = useMemo(
    () => (defaultViewEnabled ? filterExecutable(sortedItems, rowStatusMap) : sortedItems),
    [defaultViewEnabled, sortedItems, rowStatusMap],
  )
  const displayItems = defaultViewEnabled && !showAll ? executableItems : sortedItems
  const hiddenCount = defaultViewEnabled ? sortedItems.length - executableItems.length : 0

  const load = useCallback(() => {
    apiClient<TodayItemsResponse>('/api/study/today')
      .then(r => setData(r.data))
      .catch(e => setError(String(e)))
  }, [])

  useEffect(() => { load() }, [load])
  useOnActiveUserChanged(load)

  const handleProcess = async () => {
    setProcessing(true)
    try {
      const res = await apiPost<TaskSubmitResponse>('/api/study/process')
      if (res.data?.task_id) {
        setActiveTask(res.data.task_id)
      }
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
          <h2 className="text-2xl font-bold">今日任务</h2>
          <p className="text-gray-500">{data ? `${data.count} 个单词待处理` : '加载中...'}</p>
        </div>
        <button
          onClick={handleProcess}
          disabled={processing || !data?.count}
          className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {processing ? <Loader2 size={16} className="animate-spin" /> : <PlayCircle size={16} />}
          全部处理
        </button>
      </div>

      {/* V1-T1: 默认视图筛选条（flag 控制） */}
      {defaultViewEnabled && data && items.length > 0 && (
        <div className="mb-3 flex items-center gap-3 text-sm">
          <button
            onClick={() => setShowAll(v => !v)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-gray-300 hover:bg-gray-50 transition-colors text-gray-700"
            title="切换列表显示范围"
          >
            <Filter size={14} />
            {showAll
              ? `查看全部 (${sortedItems.length})`
              : `仅可执行 (${executableItems.length})`}
          </button>
          {!showAll && hiddenCount > 0 && (
            <span className="text-xs text-gray-500">
              已隐藏 {hiddenCount} 条已完成/跳过项
            </span>
          )}
          <span className="text-xs text-gray-400">价值优先 · 时间压力次级</span>
        </div>
      )}

      {error && <div className="bg-red-50 text-red-700 p-3 rounded mb-4">{error}</div>}

      {data && displayItems.length > 0 && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-4 py-2 font-medium text-gray-600">#</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">单词</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">释义</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">进度</th>
              </tr>
            </thead>
            <tbody>
              {displayItems.map((item, i) => (
                <tr key={item.voc_id} className="border-t hover:bg-gray-50">
                  <td className="px-4 py-2 text-gray-400">{i + 1}</td>
                  <td className="px-4 py-2 font-medium">{item.voc_spelling}</td>
                  <td className="px-4 py-2 text-gray-600">{item.voc_meanings || '—'}</td>
                  <td className="px-4 py-2">
                    <span
                      className="text-xs px-2 py-1 rounded bg-gray-100 text-gray-700"
                      title={
                        [
                          rowPhaseLabel(rowStatusMap[item.voc_spelling.toLowerCase()]?.phase),
                          rowStatusMap[item.voc_spelling.toLowerCase()]?.reason || '',
                        ].filter(Boolean).join(' | ')
                      }
                    >
                      {rowDisplayLabel(rowStatusMap[item.voc_spelling.toLowerCase()])}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 空状态：区分"完全无待处理" vs "筛选后无项" */}
      {data && items.length === 0 && (
        <div className="text-center py-12 text-gray-400">🎉 今日无待处理单词</div>
      )}
      {data && items.length > 0 && displayItems.length === 0 && (
        <div className="text-center py-12 text-gray-400">
          所有项均已完成或跳过 · 点"查看全部"可显示完整列表
        </div>
      )}
    </div>
  )
}
