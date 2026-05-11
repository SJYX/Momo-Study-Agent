/**
 * pages/TodayTasksV2.tsx — Today 任务页重绘版本。Spec §4。
 *
 * 复用 useTodayController（数据 + 状态机 + 业务逻辑全部不动），
 * 只换渲染：Hero 4 态 + 紧凑表格 + 暖色 pill。
 */
import { useMemo, useRef } from 'react'
import { Filter, Eye, EyeOff, Info, RotateCw } from 'lucide-react'
import { rowStatusLabel, rowPhaseLabel } from '../utils/rowProgress'
import { useTodayController } from '../hooks/useTodayController'
import ErrorBanner from '../components/ui/ErrorBanner'
import LightConfirmBar from '../components/today/LightConfirmBar'
import FailureGroupsPanel from '../components/today/FailureGroupsPanel'
import BulkGuardModal from '../components/today/BulkGuardModal'
import TodayHero from '../components/today/TodayHero'

export default function TodayTasksV2() {
  const rowRefs = useRef<Map<string, HTMLTableRowElement>>(new Map())
  const c = useTodayController(rowRefs)

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
    c.items.length - c.statusCounts.done - c.statusCounts.error - c.statusCounts.skipped - runningCount,
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
            {c.data ? `${c.data.count} 个单词待处理` : '加载中...'}
            {c.data?.ts && !c.refreshing && (
              <span className="text-xs text-text-muted">
                (数据更新于 {new Date(c.data.ts * 1000).toLocaleTimeString()})
              </span>
            )}
          </p>
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
      />

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
          {/* 筛选条 */}
          {c.flags.defaultView && c.data && c.items.length > 0 && (
            <>
              <div className="mt-4 mb-2 flex items-center gap-3 text-sm">
                <button
                  onClick={() => c.setShowAll((v) => !v)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-button border border-border-default hover:bg-surface-hover transition-colors text-text-secondary"
                >
                  <Filter size={14} />
                  {c.showAll ? `查看全部 (${c.sortedItems.length})` : `仅可执行 (${c.executableItems.length})`}
                </button>
                {!c.showAll && c.hiddenCount > 0 && (
                  <span className="text-xs text-text-muted">已隐藏 {c.hiddenCount} 条已完成/跳过项</span>
                )}
                <span className="text-xs text-text-muted">价值优先 · 时间压力次级</span>
                {c.flags.followRunning && c.isTaskRunning && (
                  <button
                    onClick={() => c.setFollowPaused((v) => !v)}
                    className="flex items-center gap-1 px-2 py-1 rounded-pill text-xs border border-border-default hover:bg-surface-hover transition-colors text-text-secondary ml-auto"
                  >
                    {c.followPaused ? <><Eye size={12} /> 恢复跟随</> : <><EyeOff size={12} /> 暂停跟随</>}
                  </button>
                )}
              </div>
              {c.isTaskRunning && (
                <div className="mb-2 flex items-center gap-1.5 text-xs text-accent">
                  <Info size={12} />
                  筛选仅影响显示，不影响正在执行的任务
                </div>
              )}
            </>
          )}

          <ErrorBanner message={c.errorMsg} size="base" />

          {c.data && c.displayItems.length > 0 && (
            <div className="bg-surface-card rounded-card shadow-card overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-surface-hover">
                  <tr>
                    <th className="text-left px-4 py-2 font-medium text-text-secondary">#</th>
                    <th className="text-left px-4 py-2 font-medium text-text-secondary">单词</th>
                    <th className="text-left px-4 py-2 font-medium text-text-secondary">进度</th>
                  </tr>
                </thead>
                <tbody>
                  {c.displayItems.map((item, i) => {
                    const state = c.rowStatusMap[item.voc_spelling.toLowerCase()]
                    const status = state?.status || 'pending'
                    const phase = state?.phase
                    const isRunning = status === 'running'
                    const pillClass = {
                      pending: 'bg-surface-hover text-text-secondary',
                      running: 'bg-accent-soft text-accent-hover border border-accent',
                      done: 'bg-surface-hover text-text-secondary',
                      error: 'bg-error-soft text-error',
                      warning: 'bg-accent-soft text-accent-hover',
                    }[status as 'pending' | 'running' | 'done' | 'error' | 'warning']
                    return (
                      <tr
                        key={item.voc_id}
                        className={`border-t border-border-soft hover:bg-surface-hover ${isRunning ? 'bg-surface-highlight' : ''}`}
                        ref={(el) => {
                          const k = (item.voc_spelling || '').toLowerCase()
                          if (el) rowRefs.current.set(k, el)
                          else rowRefs.current.delete(k)
                        }}
                      >
                        <td className="px-4 py-2 text-text-muted">{i + 1}</td>
                        <td className="px-4 py-2 font-medium text-text-primary">{item.voc_spelling}</td>
                        <td className="px-4 py-2">
                          <div className="flex flex-col gap-1">
                            <div className={`inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded-pill w-fit font-medium ${pillClass}`}>
                              {isRunning && <RotateCw size={10} className="animate-spin" />}
                              {rowStatusLabel(status as 'pending' | 'running' | 'done' | 'error' | 'warning')}
                            </div>
                            {phase && phase !== status && (
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
    </div>
  )
}
