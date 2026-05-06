/**
 * pages/TodayTasks.tsx — 今日任务列表 + 触发处理。
 *
 * V1-T1（flag: ff_today_default_view）：
 *   - 行视图保持（沿用现有表格）
 *   - 默认筛选"仅可执行项"（V1 近似：phase != 'skipped' && status != 'done'）
 *   - 价值优先 + 时间压力次级排序（V1 近似见 utils/todayView.ts）
 *   - 一键"查看全部"切换
 *   flag 关闭时回退到原始行为，列表不排序、不筛选。
 *
 * V1-T2（flag: ff_today_light_confirm）：
 *   - 点击"全部处理"后先展示轻确认条（LightConfirmBar）
 *   - 用户确认后才真正触发执行
 *   flag 关闭时直接执行，不显示确认条。
 *
 * V1-T3（flag: ff_today_follow_running）：
 *   - 执行中自动滚动到首个 running 行
 *   - 提供"暂停跟随"开关，避免干扰手动查看
 *   - 执行中改筛选时提示"仅影响显示"
 *   flag 关闭时不自动滚动。
 *
 * V1-T4（flag: ff_today_summary_stay）：
 *   - 任务终态时停留在结果摘要区，不跳回顶部
 *   - 呈现完成状态、数量统计，并提供"进入失败分组"入口
 *   flag 关闭时不渲染摘要面板。
 *
 * V1-T5（flag: ff_today_failure_groups）：
 *   - 支持点击"进入失败分组"后切换到失败分组视图
 *   - 隐藏主列表，展示按错误特征聚合的手风琴列表
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiClient, apiPost } from '../api/client'
import { useOnActiveUserChanged } from '../hooks/useOnActiveUserChanged'
import { useTaskStore } from '../stores/tasks'
import type { TodayItemsResponse, TaskSubmitResponse } from '../api/types'
import { PlayCircle, Loader2, Filter, Eye, EyeOff, Info, RotateCw, Square } from 'lucide-react'
import { buildRowStatusMap, rowStatusLabel, rowPhaseLabel } from '../utils/rowProgress'
import { isEnabled, BULK_RETRY_THRESHOLD } from '../utils/featureFlags'
import { filterExecutable, findRunningKey, sortByValue } from '../utils/todayView'
import { buildFailureGroups } from '../utils/failureGrouping'
import LightConfirmBar from '../components/today/LightConfirmBar'
import SummaryPanel from '../components/today/SummaryPanel'
import FailureGroupsPanel from '../components/today/FailureGroupsPanel'
import BulkGuardModal from '../components/today/BulkGuardModal'

export default function TodayTasks() {
  const [data, setData] = useState<TodayItemsResponse | null>(null)
  const [error, setError] = useState('')
  const [processing, setProcessing] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [showAll, setShowAll] = useState(false)
  // V1-T2：确认流程状态（idle → confirming → executing → idle）
  const [confirmingProcess, setConfirmingProcess] = useState(false)
  // V1-T7：大批量二次确认状态
  const [confirmingBulk, setConfirmingBulk] = useState(false)
  // V1-T3：暂停跟随状态
  const [followPaused, setFollowPaused] = useState(false)
  // V1-T5：失败分组视图模式
  const [showFailureMode, setShowFailureMode] = useState(false)
  // V1-T3：行 DOM 引用 Map（key = lowercase spelling）
  const rowRefs = useRef<Map<string, HTMLTableRowElement>>(new Map())
  const setActiveTask = useTaskStore(s => s.setActiveTask)
  const activeTaskId = useTaskStore(s => s.activeTaskId)
  const events = useTaskStore(s => s.events)
  const taskStatus = useTaskStore(s => s.taskStatus)
  const items = data?.items ?? []
  const rowStatusMap = buildRowStatusMap(items, events, taskStatus)

  // V1-T1：flag 开启时改造默认视图。flag 关闭时维持原始顺序与不筛选。
  const defaultViewEnabled = isEnabled('ff_today_default_view')
  // V1-T2：轻确认 flag
  const lightConfirmEnabled = isEnabled('ff_today_light_confirm')
  // V1-T3：自动跟随 flag
  const followRunningEnabled = isEnabled('ff_today_follow_running')
  // V1-T4：完成后摘要停留 flag
  const summaryStayEnabled = isEnabled('ff_today_summary_stay')
  // V1-T5：失败分组 flag
  const failureGroupsEnabled = isEnabled('ff_today_failure_groups')
  // V1-T7：大批量二次确认 flag
  const bulkGuardEnabled = isEnabled('ff_today_bulk_guard')
  const sortedItems = useMemo(
    () => (defaultViewEnabled ? sortByValue(items) : items),
    [defaultViewEnabled, items],
  )
  const executableItems = useMemo(
    () => (defaultViewEnabled ? filterExecutable(sortedItems, rowStatusMap) : sortedItems),
    [defaultViewEnabled, sortedItems, rowStatusMap],
  )
  const displayItems = useMemo(() => {
    let list = defaultViewEnabled && !showAll ? executableItems : sortedItems
    
    // 动态置顶：如果任务正在运行，将状态为 'running' 的单词移到列表最上方
    if (taskStatus === 'running' || taskStatus === 'pending') {
      list = [...list].sort((a, b) => {
        const aStatus = rowStatusMap[(a.voc_spelling || '').toLowerCase()]?.status
        const bStatus = rowStatusMap[(b.voc_spelling || '').toLowerCase()]?.status
        if (aStatus === 'running' && bStatus !== 'running') return -1
        if (aStatus !== 'running' && bStatus === 'running') return 1
        return 0
      })
    }
    return list
  }, [defaultViewEnabled, showAll, executableItems, sortedItems, taskStatus, rowStatusMap])
  
  const hiddenCount = defaultViewEnabled ? sortedItems.length - executableItems.length : 0

  // V1-T3：当前 running 行 key
  const runningKey = useMemo(() => findRunningKey(rowStatusMap), [rowStatusMap])
  const isTaskRunning = taskStatus === 'running' || taskStatus === 'pending'
  
  // V1-T4：终态与统计计算
  const isTerminal = taskStatus === 'done' || taskStatus === 'error' || taskStatus === 'canceled'
  const statusCounts = useMemo(() => {
    let done = 0, error = 0, skipped = 0
    for (const s of Object.values(rowStatusMap)) {
      if (!s) continue
      if (s.phase === 'skipped') skipped++
      else if (s.status === 'done') done++
      else if (s.status === 'error') error++
    }
    return { done, error, skipped }
  }, [rowStatusMap])

  // V1-T5：计算失败分组数据
  const failureGroups = useMemo(() => {
    if (!failureGroupsEnabled || !showFailureMode) return []
    return buildFailureGroups(items, rowStatusMap)
  }, [items, rowStatusMap, failureGroupsEnabled, showFailureMode])

  const load = useCallback((refresh: boolean = false) => {
    if (refresh) setRefreshing(true)
    const url = refresh ? '/api/study/today?refresh=true' : '/api/study/today'
    apiClient<TodayItemsResponse>(url)
      .then(r => setData(r.data))
      .catch(e => setError(String(e)))
      .finally(() => setRefreshing(false))
  }, [])

  useEffect(() => { load() }, [load])
  useOnActiveUserChanged(() => load())

  // V1-T3：自动滚动到 running 行
  const scrollToRow = useCallback((key: string) => {
    const el = rowRefs.current.get(key)
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [])

  useEffect(() => {
    if (!followRunningEnabled || followPaused || !runningKey) return
    scrollToRow(runningKey)
  }, [followRunningEnabled, followPaused, runningKey, scrollToRow])

  // V1-T3：任务终态时重置暂停状态
  useEffect(() => {
    if (taskStatus === 'done' || taskStatus === 'error' || taskStatus === 'idle') {
      setFollowPaused(false)
    }
  }, [taskStatus])

  const handleProcess = async (voc_ids?: string[]) => {
    setProcessing(true)
    try {
      const payload = voc_ids ? { voc_ids } : {}
      const res = await apiPost<TaskSubmitResponse>('/api/study/process', payload)
      if (res.data?.task_id) {
        setActiveTask(res.data.task_id)
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setProcessing(false)
      setConfirmingProcess(false)
    }
  }

  // V1-T2：按钮点击入口，flag ON 时走确认流程，OFF 时直接执行
  const handleClick = () => {
    if (bulkGuardEnabled && executableItems.length > BULK_RETRY_THRESHOLD) {
      setConfirmingBulk(true)
    } else if (lightConfirmEnabled) {
      setConfirmingProcess(true)
    } else {
      handleProcess()
    }
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-bold">今日任务</h2>
            <button
              onClick={() => load(true)}
              disabled={refreshing || processing}
              className="p-1.5 rounded-full hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-all active:scale-90 disabled:opacity-30"
              title="强制从墨墨 API 刷新列表"
            >
              <RotateCw size={18} className={refreshing ? 'animate-spin' : ''} />
            </button>
          </div>
          <p className="text-gray-500 flex items-center gap-2">
            {data ? `${data.count} 个单词待处理` : '加载中...'}
            {data?.ts && !refreshing && (
              <span className="text-xs text-gray-300">
                (数据更新于 {new Date(data.ts * 1000).toLocaleTimeString()})
              </span>
            )}
          </p>
        </div>
        {isTaskRunning ? (
          <button
            onClick={async () => {
              if (!activeTaskId) return
              setProcessing(true)
              try {
                await apiPost(`/api/tasks/${activeTaskId}/cancel`)
              } catch (e) {
                setError(String(e))
              } finally {
                setProcessing(false)
              }
            }}
            disabled={processing}
            className="flex items-center gap-2 bg-red-500 text-white px-4 py-2 rounded-lg hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
          >
            {processing ? <Loader2 size={16} className="animate-spin" /> : <Square size={16} />}
            停止处理
          </button>
        ) : (
          <button
            onClick={handleClick}
            disabled={processing || refreshing || confirmingProcess || !data?.count}
            className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {processing ? <Loader2 size={16} className="animate-spin" /> : <PlayCircle size={16} />}
            全部处理
          </button>
        )}
      </div>

      {/* V1-T4: 结果摘要面板（终态时展示） */}
      {summaryStayEnabled && isTerminal && items.length > 0 && (
        <SummaryPanel
          doneCount={statusCounts.done}
          errorCount={statusCounts.error}
          skippedCount={statusCounts.skipped}
          totalCount={items.length}
          taskStatus={taskStatus}
          onGoToFailures={failureGroupsEnabled ? () => setShowFailureMode(true) : undefined}
        />
      )}

      {/* V1-T2: 轻确认条（flag 控制） */}
      {confirmingProcess && (
        <LightConfirmBar
          count={executableItems.length}
          onConfirm={handleProcess}
          onCancel={() => setConfirmingProcess(false)}
          loading={processing}
        />
      )}

      {/* V1-T7: 大批量二次确认弹窗 */}
      {confirmingBulk && (
        <BulkGuardModal
          count={executableItems.length}
          onConfirm={() => {
            setConfirmingBulk(false)
            handleProcess()
          }}
          onCancel={() => setConfirmingBulk(false)}
        />
      )}

      {showFailureMode && failureGroupsEnabled ? (
        <FailureGroupsPanel
          groups={failureGroups}
          rowStatusMap={rowStatusMap}
          onBack={() => setShowFailureMode(false)}
          onRetryGroup={isEnabled('ff_today_group_retry') ? (g) => handleProcess(g.items.map(it => it.voc_id)) : undefined}
        />
      ) : (
        <>
          {/* V1-T1: 默认视图筛选条（flag 控制） */}
          {defaultViewEnabled && data && items.length > 0 && (
            <>
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
          {/* V1-T3: 暂停/恢复跟随按钮（执行中 + flag ON 时显示） */}
          {followRunningEnabled && isTaskRunning && (
            <button
              onClick={() => setFollowPaused(v => !v)}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs border border-gray-300 hover:bg-gray-50 transition-colors text-gray-600 ml-auto"
              title={followPaused ? '恢复自动跟随当前处理行' : '暂停自动跟随'}
            >
              {followPaused ? <><Eye size={12} /> 恢复跟随</> : <><EyeOff size={12} /> 暂停跟随</>}
            </button>
          )}
        </div>
        {/* V1-T3: 执行中筛选提示 */}
        {isTaskRunning && (
          <div className="mb-2 flex items-center gap-1.5 text-xs text-amber-600">
            <Info size={12} />
            筛选仅影响显示，不影响正在执行的任务
          </div>
        )}
        </>
      )}

      {error && <div className="bg-red-50 text-red-700 p-3 rounded mb-4">{error}</div>}

      {data && displayItems.length > 0 && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-4 py-2 font-medium text-gray-600">#</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">单词</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">进度</th>
              </tr>
            </thead>
            <tbody>
              {displayItems.map((item, i) => (
                <tr
                  key={item.voc_id}
                  className="border-t hover:bg-gray-50"
                  ref={el => {
                    const k = (item.voc_spelling || '').toLowerCase()
                    if (el) rowRefs.current.set(k, el); else rowRefs.current.delete(k)
                  }}
                >
                  <td className="px-4 py-2 text-gray-400">{i + 1}</td>
                  <td className="px-4 py-2 font-medium">{item.voc_spelling}</td>
                  <td className="px-4 py-2">
                    {(() => {
                      const state = rowStatusMap[item.voc_spelling.toLowerCase()]
                      const status = state?.status || 'pending'
                      const phase = state?.phase
                      
                      const colors = {
                        pending: 'bg-gray-100 text-gray-500',
                        running: 'bg-blue-50 text-blue-600 border border-blue-100',
                        done: 'bg-green-50 text-green-600',
                        error: 'bg-red-50 text-red-600',
                        warning: 'bg-amber-50 text-amber-600 border border-amber-100',
                      }

                      return (
                        <div className="flex flex-col gap-1">
                          <div className={`inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded w-fit font-medium ${colors[status as keyof typeof colors]}`}>
                            {status === 'running' && <Loader2 size={10} className="animate-spin" />}
                            {rowStatusLabel(status as any)}
                          </div>
                          {phase && phase !== status && (
                            <span className={`text-[10px] font-normal ml-0.5 ${status === 'error' ? 'text-red-400' : status === 'warning' ? 'text-amber-500' : status === 'done' ? 'text-green-500/80' : 'text-blue-400'}`}>
                              {rowPhaseLabel(phase)}
                            </span>
                          )}
                          {(status === 'error' || status === 'warning') && state.reason && (
                            <span className={`text-[10px] font-normal ml-0.5 max-w-[150px] truncate ${status === 'error' ? 'text-red-400' : 'text-amber-500'}`}>
                              {state.reason}
                            </span>
                          )}
                        </div>
                      )
                    })()}
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
        </>
      )}
    </div>
  )
}
