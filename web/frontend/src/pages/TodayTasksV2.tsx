/**
 * pages/TodayTasksV2.tsx — Today 任务页重绘版本。Spec §4。
 *
 * 复用 useTodayController（数据 + 状态机 + 业务逻辑全部不动），
 * 只换渲染：Hero 4 态 + 紧凑表格 + 暖色 pill。
 */
import { useMemo, useRef } from 'react'
import { Eye, EyeOff, Info, RotateCw, CloudDownload, Square, AlertTriangle } from 'lucide-react'
import { rowPhaseLabel, rowDisplayLabel } from '../utils/rowProgress'
import { useTodayController } from '../hooks/useTodayController'
import ErrorBanner from '../components/ui/ErrorBanner'
import LightConfirmBar from '../components/today/LightConfirmBar'
import FailureGroupsPanel from '../components/today/FailureGroupsPanel'
import BulkGuardModal from '../components/today/BulkGuardModal'
import TodayHero from '../components/today/TodayHero'
import BottomBar from '../components/today/BottomBar'
import { Link, useSearchParams } from 'react-router-dom'
import { parseDrillDownParams, isDrillDownActive, drillDownLabel } from '../utils/drillDown'
import { isEnabled } from '../utils/featureFlags'
import DrillDownNotice from '../components/today/DrillDownNotice'

export default function TodayTasksV2() {
  const rowRefs = useRef<Map<string, HTMLTableRowElement>>(new Map())
  const c = useTodayController(rowRefs)

  const [searchParams, setSearchParams] = useSearchParams()
  const drill = parseDrillDownParams(searchParams)
  const drillActive = isEnabled('ff_drilldown_v2') && isDrillDownActive(drill)

  const clearDrillDown = () => {
    const next = new URLSearchParams(searchParams)
    next.delete('error_type')
    next.delete('window')
    setSearchParams(next, { replace: true })
  }

  // 找当前 running 词 + phase（rowStatusMap 的 key 是 lowercase，从 items 拿原始大小写）
  const runningItem = c.items.find(
    (it) => c.rowStatusMap[(it.voc_spelling || '').toLowerCase()]?.status === 'running',
  )
  const currentWord = runningItem?.voc_spelling ?? null
  const currentPhase = runningItem
    ? c.rowStatusMap[(runningItem.voc_spelling || '').toLowerCase()]?.phase ?? null
    : null

  // statusCounts 只有 done/error/skipped；running/pending 本地补
  const runningCount = useMemo(
    () => Object.values(c.rowStatusMap).filter((s) => s?.status === 'running').length,
    [c.rowStatusMap],
  )
  const pendingCount = Math.max(
    0,
    c.items.filter((it) => {
      const s = c.rowStatusMap[(it.voc_spelling || '').toLowerCase()]
      if (!s) return true
      if (s.phase === 'sync_conflict') return false
      return s.status === 'pending'
    }).length,
  )

  const conflictCount = useMemo(
    () => Object.values(c.rowStatusMap).filter((s) => s?.phase === 'sync_conflict').length,
    [c.rowStatusMap],
  )

  return (
    <div className="p-6 bg-surface-base min-h-screen">
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-bold text-text-primary">今日任务</h2>
            <button
              onClick={c.refresh}
              disabled={c.refreshing || c.processing}
              className="p-1.5 rounded-pill hover:bg-surface-hover text-text-muted hover:text-text-primary transition-all active:scale-90 disabled:opacity-30"
              title="强制从墨墨 API 刷新列表"
            >
              <RotateCw size={16} className={c.refreshing ? 'animate-spin' : ''} />
            </button>
          </div>
          <p className="text-text-secondary text-sm flex items-center gap-2">
            {c.data ? `${c.executableItems.length} 个单词待处理` : '加载中...'}
            {c.data?.ts && !c.refreshing && (
              <span className="text-xs text-text-muted">
                (数据更新于 {new Date(c.data.ts * 1000).toLocaleTimeString()})
              </span>
            )}
          </p>
          {conflictCount > 0 && (
            <div className="mt-2">
              <Link
                to="/today/conflicts"
                className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-pill border border-error/30 bg-error-soft text-error hover:opacity-90"
              >
                <AlertTriangle size={12} />
                {conflictCount} 个冲突词，进入冲突页面
              </Link>
            </div>
          )}
        </div>
      </div>

      {/* Hero */}
      <TodayHero
        isTaskRunning={c.isTaskRunning}
        isTerminal={c.isTerminal}
        totalCount={c.items.length}
        executableCount={c.executableItems.length}
        doneCount={c.statusCounts.done}
        errorCount={c.statusCounts.error}
        skippedCount={c.statusCounts.skipped}
        runningCount={runningCount}
        pendingCount={pendingCount}
        currentWord={currentWord}
        currentPhase={currentPhase}
        showAll={c.showAll}
        onStart={c.handleClick}
        onCancel={() => c.handleCancel()}
        onToggleShowAll={() => c.setShowAll((v) => !v)}
        onViewFailures={c.flags.failureGroups ? () => c.setShowFailureMode(true) : undefined}
        onRetryBatch={() => c.refresh()}
        disabled={c.processing || c.refreshing || c.confirmingProcess}
        filteredCount={c.filteredItemsCount}
        filterView={c.filterView}
        onRetryFailures={c.statusCounts.error > 0 ? () => c.handleProcess(c.items.filter(it => c.rowStatusMap[(it.voc_spelling||'').toLowerCase()]?.status === 'error').map(it => it.voc_id)) : undefined}
      />

      {drillActive && (
        <DrillDownNotice label={drillDownLabel(drill)} onClear={clearDrillDown} />
      )}

      {/* V1-T2: 轻确认条 */}
      {c.confirmingProcess && (
        <div className="mt-4">
          <LightConfirmBar
            count={c.executableItems.length}
            onConfirm={() => c.handleProcess()}
            onCancel={() => c.setConfirmingProcess(false)}
            loading={c.processing}
          />
        </div>
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
        <div className="mt-4">
          <FailureGroupsPanel
            groups={c.failureGroups}
            rowStatusMap={c.rowStatusMap}
            onBack={() => c.setShowFailureMode(false)}
            onRetryGroup={c.flags.groupRetry ? (g) => c.handleProcess(g.items.map((it) => it.voc_id)) : undefined}
          />
        </div>
      ) : (
        <>
          {/* 筛选条（新版 Filter Bar） */}
          {c.flags.defaultView && c.data && c.items.length > 0 && (
            <>
              <div className="mt-4 mb-3 flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                  {(['all', 'pending', 'error', 'new', 'review'] as const).map(view => {
                    const label = {
                      all: `全部 (${c.items.length})`,
                      pending: `待处理`,
                      error: `已失败`,
                      new: `新词`,
                      review: `复习词`
                    }[view]
                    return (
                      <button
                        key={view}
                        onClick={() => c.setFilterView(view)}
                        className={`px-3 py-1.5 rounded-pill border text-xs font-medium transition-colors ${
                          c.filterView === view 
                            ? 'bg-surface-hover text-text-primary border-border-default' 
                            : 'bg-transparent text-text-secondary border-transparent hover:bg-surface-hover/50'
                        }`}
                      >
                        {label}
                      </button>
                    )
                  })}
                </div>
                <div className="flex items-center gap-3">
                   {!c.isBatchMode && (
                     <button
                       onClick={() => c.setIsBatchMode(true)}
                       className="flex items-center gap-1.5 text-text-secondary hover:text-text-primary text-xs"
                     >
                       <Square size={14} /> 进入批量选择
                     </button>
                   )}
                  {c.flags.followRunning && c.isTaskRunning && (
                    <button
                      onClick={() => c.setFollowPaused((v) => !v)}
                      className="flex items-center gap-1 px-2 py-1 rounded-pill text-xs border border-border-default hover:bg-surface-hover transition-colors text-text-secondary"
                    >
                      {c.followPaused ? <><Eye size={12} /> 恢复跟随</> : <><EyeOff size={12} /> 暂停跟随</>}
                    </button>
                  )}
                </div>
              </div>
              {c.isTaskRunning && (
                <div className="mb-2 flex items-center gap-1.5 text-xs text-accent">
                  <Info size={12} />
                  筛选仅影响显示，不影响正在执行的任务
                </div>
              )}
            </>
          )}

          {/* DB 同步中提示 */}
          {c.dbSyncing && !c.data && (
            <div className="flex items-center gap-2 mb-3 px-4 py-2.5 bg-blue-50 border border-blue-200 rounded-lg text-blue-700 text-sm">
              <CloudDownload size={16} className="animate-pulse" />
              <span>正在从云端同步数据库，初次启动可能需要几秒...</span>
            </div>
          )}

          <ErrorBanner message={c.errorMsg} size="base" />

          {c.data && c.displayItems.length > 0 && (
            <div className="bg-surface-card rounded-card shadow-card overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-surface-hover">
                  <tr>
                        {c.isBatchMode && (
                          <th className="px-4 py-2 w-10" />
                        )}
                        <th className="text-left px-4 py-2 font-medium text-text-secondary">#</th>
                        <th className="text-left px-4 py-2 font-medium text-text-secondary">单词</th>
                        <th className="text-left px-4 py-2 font-medium text-text-secondary">进度</th>
                        <th className="px-4 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {c.displayItems.map((item, i) => {
                    const state = c.rowStatusMap[item.voc_spelling.toLowerCase()]
                    const status = state?.status || 'pending'
                    const phase = state?.phase
                    const isRunning = status === 'running'
                        const isError = status === 'error'
                        const isSelected = c.selectedIds.has(item.voc_id)
                    let pillClass = {
                      pending: 'bg-surface-hover text-text-secondary',
                      running: 'bg-accent-soft text-accent-hover border border-accent',
                      done: 'bg-surface-hover text-text-secondary',
                      error: 'bg-error-soft text-error',
                      warning: 'bg-accent-soft text-accent-hover',
                    }[status as 'pending' | 'running' | 'done' | 'error' | 'warning']
                    if (status === 'done' && phase && phase.startsWith('sync_')) {
                      pillClass = 'bg-accent-soft/30 text-accent-hover'
                    }
                    return (
                      <tr
                        key={item.voc_id}
                        onClick={c.isBatchMode ? () => {
                          const next = new Set(c.selectedIds)
                          if (next.has(item.voc_id)) next.delete(item.voc_id)
                          else next.add(item.voc_id)
                          c.setSelectedIds(next)
                        } : undefined}
                        className={`border-t border-border-soft transition-all duration-300 ${
                          c.isBatchMode ? 'cursor-pointer' : ''
                        } ${
                          isRunning ? 'bg-surface-highlight animate-pulse' : 
                          isError ? 'bg-error-soft/30' : 'hover:bg-surface-hover'
                        }`}
                        ref={(el) => {
                          const k = (item.voc_spelling || '').toLowerCase()
                          if (el) rowRefs.current.set(k, el)
                          else rowRefs.current.delete(k)
                        }}
                      >
                        {c.isBatchMode && (
                          <td className="px-4 py-2 w-10">
                            <input 
                              type="checkbox" 
                              checked={isSelected} 
                              readOnly
                              className="w-4 h-4 rounded border-border-default text-accent focus:ring-accent/20" 
                            />
                          </td>
                        )}
                        <td className="px-4 py-2 text-text-muted">{i + 1}</td>
                        <td className="px-4 py-2 font-medium text-text-primary">{item.voc_spelling}</td>
                        <td className="px-4 py-2">
                          <div className="flex flex-col gap-1">
                            <div className={`inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded-pill w-fit font-medium ${pillClass}`}>
                              {isRunning && <RotateCw size={10} className="animate-spin" />}
                              {rowDisplayLabel(state)}
                            </div>
                            {phase && phase !== status && rowPhaseLabel(phase) !== rowDisplayLabel(state) && (
                              <span className={`text-[10px] font-normal ml-0.5 ${
                                status === 'error' ? 'text-error' :
                                status === 'warning' ? 'text-accent' :
                                status === 'done' ? 'text-text-muted' : 'text-accent'
                              }`}>
                                {rowPhaseLabel(phase)}
                              </span>
                            )}
                            {(status === 'error' || status === 'warning') && state.reason && (
                              <span className={`text-[10px] font-normal ml-0.5 max-w-[200px] truncate ${status === 'error' ? 'text-error' : 'text-accent'}`}>
                                {state.reason}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-2 text-right">
                           {isError && !c.isBatchMode && (
                             <button
                               onClick={(e) => { e.stopPropagation(); c.handleProcess([item.voc_id]) }}
                               className="text-error hover:text-error/80 text-xs px-2 py-1 rounded border border-error/30 hover:bg-error-soft transition-colors"
                             >
                               ↻ 重试
                             </button>
                           )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {c.data && c.items.length > 0 && c.displayItems.length === 0 && (
            <div className="text-center py-12 text-text-muted">
              所有项均已完成或跳过 · 点"查看全部"可显示完整列表
            </div>
          )}
        </>
      )}

      {c.isBatchMode && (
        <BottomBar
          selectedCount={c.selectedIds.size}
          onCancel={() => {
            c.setIsBatchMode(false)
            c.setSelectedIds(new Set())
          }}
          onProcess={() => {
            c.handleProcess(Array.from(c.selectedIds))
            c.setIsBatchMode(false)
            c.setSelectedIds(new Set())
          }}
          disabled={c.processing}
        />
      )}
    </div>
  )
}
