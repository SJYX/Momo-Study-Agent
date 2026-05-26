/**
 * pages/TodayTasks.tsx — 今日任务列表 + 触发处理。
 *
 * V1-T1（flag: ff_today_default_view）：默认筛选"仅可执行项"+ 价值优先排序。
 * V1-T2（flag: ff_today_light_confirm）：执行前轻确认条。
 * V1-T3（flag: ff_today_follow_running）：执行中自动滚动到首个 running 行 + 暂停跟随。
 * V1-T4（flag: ff_today_summary_stay）：终态展示结果摘要面板。
 * V1-T5（flag: ff_today_failure_groups）：进入失败分组视图。
 * V1-T7（flag: ff_today_bulk_guard）：大批量二次确认。
 *
 * 状态机/数据/副作用全部由 useTodayController 承担；本组件只做渲染编排。
 */
import { useRef } from 'react'
import { PlayCircle, Loader2, Filter, Eye, EyeOff, Info, RotateCw, Square, CloudDownload } from 'lucide-react'
import { rowPhaseLabel, rowDisplayLabel } from '../utils/rowProgress'
import { useTodayController } from '../hooks/useTodayController'
import ErrorBanner from '../components/ui/ErrorBanner'
import { SkeletonRow } from '../components/ui/Skeleton'
import LightConfirmBar from '../components/today/LightConfirmBar'
import SummaryPanel from '../components/today/SummaryPanel'
import FailureGroupsPanel from '../components/today/FailureGroupsPanel'
import BulkGuardModal from '../components/today/BulkGuardModal'
import { isEnabled } from '../utils/featureFlags'
import TodayTasksV2 from './TodayTasksV2'

export default function TodayTasks() {
  // eslint-disable-next-line react-hooks/rules-of-hooks
  if (isEnabled('ff_redesign_today')) return <TodayTasksV2 />

  // DOM ref Map（hook 不持有 DOM；只通过它询问当前 running 行）
  const rowRefs = useRef<Map<string, HTMLTableRowElement>>(new Map())
  const c = useTodayController(rowRefs)

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-bold">今日任务</h2>
            <button
              onClick={c.refresh}
              disabled={c.refreshing || c.processing}
              className="p-1.5 rounded-full hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-all active:scale-90 disabled:opacity-30"
              title="强制从墨墨 API 刷新列表"
            >
              <RotateCw size={18} className={c.refreshing ? 'animate-spin' : ''} />
            </button>
          </div>
          <p className="text-gray-500 flex items-center gap-2">
            {c.data ? `${c.executableItems.length} 个单词待处理` : '加载中...'}
            {c.data?.ts && !c.refreshing && (
              <span className="text-xs text-gray-300">
                (数据更新于 {new Date(c.data.ts * 1000).toLocaleTimeString()})
              </span>
            )}
          </p>
        </div>
        {c.isTaskRunning ? (
          <button
            onClick={() => c.handleCancel()}
            disabled={c.processing}
            className="flex items-center gap-2 bg-red-500 text-white px-4 py-2 rounded-lg hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
          >
            {c.processing ? <Loader2 size={16} className="animate-spin" /> : <Square size={16} />}
            停止处理
          </button>
        ) : (
          <button
            onClick={c.handleClick}
            disabled={c.processing || c.refreshing || c.confirmingProcess || !c.data?.count}
            className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {c.processing ? <Loader2 size={16} className="animate-spin" /> : <PlayCircle size={16} />}
            全部处理
          </button>
        )}
      </div>

      {/* DB 同步中提示 */}
      {c.dbSyncing && !c.data && (
        <div className="flex items-center gap-2 mb-4 px-4 py-2.5 bg-blue-50 border border-blue-200 rounded-lg text-blue-700 text-sm">
          <CloudDownload size={16} className="animate-pulse" />
          <span>正在从云端同步数据库，初次启动可能需要几秒...</span>
        </div>
      )}

      {/* V1-T4: 结果摘要面板（终态） */}
      {c.flags.summaryStay && c.isTerminal && c.items.length > 0 && (
        <SummaryPanel
          doneCount={c.statusCounts.done}
          errorCount={c.statusCounts.error}
          skippedCount={c.statusCounts.skipped}
          totalCount={c.items.length}
          taskStatus={c.taskStatus}
          onGoToFailures={c.flags.failureGroups ? () => c.setShowFailureMode(true) : undefined}
        />
      )}

      {/* V1-T2: 轻确认条 */}
      {c.confirmingProcess && (
        <LightConfirmBar
          count={c.executableItems.length}
          onConfirm={() => c.handleProcess()}
          onCancel={() => c.setConfirmingProcess(false)}
          loading={c.processing}
        />
      )}

      {/* V1-T7: 大批量二次确认 */}
      {c.confirmingBulk && (
        <BulkGuardModal
          count={c.executableItems.length}
          onConfirm={() => {
            c.setConfirmingBulk(false)
            c.handleProcess()
          }}
          onCancel={() => c.setConfirmingBulk(false)}
        />
      )}

      {c.showFailureMode && c.flags.failureGroups ? (
        <FailureGroupsPanel
          groups={c.failureGroups}
          rowStatusMap={c.rowStatusMap}
          onBack={() => c.setShowFailureMode(false)}
          onRetryGroup={c.flags.groupRetry ? (g) => c.handleProcess(g.items.map(it => it.voc_id)) : undefined}
        />
      ) : (
        <>
          {/* V1-T1: 默认视图筛选条 */}
          {c.flags.defaultView && c.data && c.items.length > 0 && (
            <>
              <div className="mb-3 flex items-center gap-3 text-sm">
                <button
                  onClick={() => c.setShowAll(v => !v)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-gray-300 hover:bg-gray-50 transition-colors text-gray-700"
                  title="切换列表显示范围"
                >
                  <Filter size={14} />
                  {c.showAll
                    ? `查看全部 (${c.sortedItems.length})`
                    : `仅可执行 (${c.executableItems.length})`}
                </button>
                {!c.showAll && c.hiddenCount > 0 && (
                  <span className="text-xs text-gray-500">
                    已隐藏 {c.hiddenCount} 条已完成/跳过项
                  </span>
                )}
                <span className="text-xs text-gray-400">价值优先 · 时间压力次级</span>
                {/* V1-T3: 暂停/恢复跟随 */}
                {c.flags.followRunning && c.isTaskRunning && (
                  <button
                    onClick={() => c.setFollowPaused(v => !v)}
                    className="flex items-center gap-1 px-2 py-1 rounded text-xs border border-gray-300 hover:bg-gray-50 transition-colors text-gray-600 ml-auto"
                    title={c.followPaused ? '恢复自动跟随当前处理行' : '暂停自动跟随'}
                  >
                    {c.followPaused ? <><Eye size={12} /> 恢复跟随</> : <><EyeOff size={12} /> 暂停跟随</>}
                  </button>
                )}
              </div>
              {c.isTaskRunning && (
                <div className="mb-2 flex items-center gap-1.5 text-xs text-amber-600">
                  <Info size={12} />
                  筛选仅影响显示，不影响正在执行的任务
                </div>
              )}
            </>
          )}

          <ErrorBanner message={c.errorMsg} size="base" />

          {!c.data && !c.errorMsg && (
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
                  {Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} cols={3} />)}
                </tbody>
              </table>
            </div>
          )}

          {c.data && c.displayItems.length > 0 && (
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
                  {c.displayItems.map((item, i) => {
                    const state = c.rowStatusMap[item.voc_spelling.toLowerCase()]
                    const status = state?.status || 'pending'
                    const phase = state?.phase
                    let colorClass = {
                      pending: 'bg-gray-100 text-gray-500',
                      running: 'bg-blue-50 text-blue-600 border border-blue-100',
                      done: 'bg-green-50 text-green-600',
                      error: 'bg-red-50 text-red-600',
                      warning: 'bg-amber-50 text-amber-600 border border-amber-100',
                    }[status as 'pending' | 'running' | 'done' | 'error' | 'warning']
                    if (status === 'done' && phase && phase.startsWith('sync_')) {
                      colorClass = 'bg-blue-50/50 text-blue-500'
                    }
                    return (
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
                          <div className="flex flex-col gap-1">
                            <div className={`inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded w-fit font-medium ${colorClass}`}>
                              {status === 'running' && <Loader2 size={10} className="animate-spin" />}
                              {rowDisplayLabel(state)}
                            </div>
                            {phase && phase !== status && rowPhaseLabel(phase) !== rowDisplayLabel(state) && (
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
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {c.data && c.items.length === 0 && (
            <div className="text-center py-12 text-gray-400">🎉 今日无待处理单词</div>
          )}
          {c.data && c.items.length > 0 && c.displayItems.length === 0 && (
            <div className="text-center py-12 text-gray-400">
              所有项均已完成或跳过 · 点"查看全部"可显示完整列表
            </div>
          )}
        </>
      )}
    </div>
  )
}
