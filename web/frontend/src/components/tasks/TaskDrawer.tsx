/**
 * components/tasks/TaskDrawer.tsx — 全局右下角悬浮任务面板。
 *
 * P4-T3 升级：从"日志主视图"改为"结构化主视图"。
 *   - 顶部：profile + 任务状态 + 当前阶段 chip
 *   - 中部：总进度条（取最新 ProgressEvent 的 current/total/phase）
 *           + 行级计数 done / error / running / pending（取自 row_status 事件累计）
 *   - 底部：日志默认折叠，按需展开
 *   - 终态：显示结果摘要
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  X, Minimize2, Loader2, CheckCircle2, XCircle, Ban, Square,
  ChevronDown, ChevronRight,
} from 'lucide-react'
import { useTaskStream } from '../../hooks/useTaskStream'
import { useTaskStore } from '../../stores/tasks'
import { useProfileStore } from '../../stores/profile'
import { apiPost } from '../../api/client'
import { rowPhaseLabel } from '../../utils/rowProgress'
import type { TaskEvent, LogEvent, ProgressEvent, RowStatusEvent, RowState } from '../../api/types'

function isLog(ev: TaskEvent): ev is LogEvent {
  return ev.type === 'log'
}
function isProgress(ev: TaskEvent): ev is ProgressEvent {
  return ev.type === 'progress'
}
function isRowStatus(ev: TaskEvent): ev is RowStatusEvent {
  return ev.type === 'row_status'
}

interface RowAggregateCounts {
  done: number
  error: number
  running: number
  pending: number
}

function aggregateRowCounts(events: TaskEvent[]): RowAggregateCounts {
  // 按 item_id 取最后一次状态（事件按时间顺序到达）
  const last: Record<string, RowState['status']> = {}
  for (const ev of events) {
    if (!isRowStatus(ev)) continue
    for (const row of ev.rows) {
      const id = String(row.item_id || '').toLowerCase()
      if (!id) continue
      last[id] = row.status
    }
  }
  const counts: RowAggregateCounts = { done: 0, error: 0, running: 0, pending: 0 }
  for (const st of Object.values(last)) {
    if (st === 'done') counts.done += 1
    else if (st === 'error') counts.error += 1
    else if (st === 'running') counts.running += 1
    else counts.pending += 1
  }
  return counts
}

function phaseChipText(phase: string | null | undefined): string {
  if (!phase) return ''
  const mapped = rowPhaseLabel(phase)
  if (mapped) return mapped
  if (phase === 'ai_batch_start') return 'AI 批次启动'
  if (phase === 'ai_batch_done') return 'AI 批次完成'
  if (phase === 'ai_batch_error') return 'AI 批次失败'
  return phase
}

export default function TaskDrawer() {
  const { activeTaskId, drawerOpen, drawerMinimized, setTaskStatus, addEvent, closeDrawer, toggleMinimize } = useTaskStore()
  const activeProfile = useProfileStore(s => s.activeProfile)
  const logEndRef = useRef<HTMLDivElement>(null)
  const [canceling, setCanceling] = useState(false)
  const [cancelError, setCancelError] = useState('')
  const [logExpanded, setLogExpanded] = useState(false)

  const { events, status } = useTaskStream({
    taskId: activeTaskId,
    enabled: drawerOpen && !!activeTaskId,
    onEvent: (e) => addEvent(e),
    onDone: (s) => setTaskStatus(s),
  })

  useEffect(() => {
    setTaskStatus(status)
  }, [status]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (logExpanded) logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events, logExpanded])

  // ⚠️ 所有 hooks 必须在 early return 之前调用，否则 drawer 从关→开时 hooks 数量变化触发 React #310。
  const logEvents = useMemo(() => events.filter(isLog), [events])
  const progressEvents = useMemo(() => events.filter(isProgress), [events])
  const counts = useMemo(() => aggregateRowCounts(events), [events])

  if (!drawerOpen || !activeTaskId) return null

  const isTerminal = ['done', 'error', 'canceled'].includes(status)
  const canCancel = ['pending', 'running', 'connected', 'connecting'].includes(status)

  const latestProgress = progressEvents.length > 0 ? progressEvents[progressEvents.length - 1] : null
  const progressCurrent = latestProgress?.current ?? 0
  const progressTotal = latestProgress?.total ?? 0
  const progressPercent = latestProgress && progressTotal > 0
    ? Math.max(0, Math.min(100, Math.round((progressCurrent / progressTotal) * 100)))
    : null
  const totalRows = counts.done + counts.error + counts.running + counts.pending

  const statusColor = status === 'done' ? 'text-green-500'
    : status === 'error' ? 'text-red-500'
    : status === 'canceled' ? 'text-yellow-500'
    : status === 'running' ? 'text-blue-500'
    : 'text-gray-400'
  const statusLabel = status === 'done' ? '已完成'
    : status === 'error' ? '出错'
    : status === 'canceled' ? '已取消'
    : status === 'running' ? '运行中'
    : status === 'pending' ? '排队中'
    : status === 'connecting' ? '连接中'
    : status === 'connected' ? '已连接'
    : status

  const handleCancel = async () => {
    if (!activeTaskId || !canCancel || canceling) return
    setCancelError('')
    setCanceling(true)
    try {
      await apiPost(`/api/tasks/${activeTaskId}/cancel`)
    } catch (e) {
      setCancelError(String(e))
    } finally {
      setCanceling(false)
    }
  }

  if (drawerMinimized) {
    return (
      <button
        onClick={toggleMinimize}
        className="fixed bottom-4 right-4 bg-gray-900 text-white rounded-full px-4 py-2 shadow-lg flex items-center gap-2 text-sm hover:bg-gray-800 transition-colors z-50"
      >
        {status === 'running' && <Loader2 size={14} className="animate-spin" />}
        {status === 'done' && <CheckCircle2 size={14} className="text-green-500" />}
        {status === 'error' && <XCircle size={14} className="text-red-500" />}
        {status === 'pending' && <Loader2 size={14} className="text-gray-400" />}
        <span className={statusColor}>{statusLabel}</span>
        {totalRows > 0 && (
          <>
            <span className="text-gray-500">·</span>
            <span className="text-green-400">{counts.done}</span>
            <span className="text-gray-500">/</span>
            <span>{totalRows}</span>
            {counts.error > 0 && <span className="text-red-400">×{counts.error}</span>}
          </>
        )}
      </button>
    )
  }

  return (
    <div className="fixed bottom-4 right-4 w-[480px] max-h-[70vh] bg-gray-900 text-gray-100 rounded-lg shadow-2xl flex flex-col z-50 border border-gray-700">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-700">
        <div className="flex items-center gap-2 text-sm font-medium">
          {status === 'running' && <Loader2 size={14} className="animate-spin text-blue-500" />}
          {status === 'pending' && <Loader2 size={14} className="text-gray-400" />}
          {status === 'done' && <CheckCircle2 size={14} className="text-green-500" />}
          {status === 'error' && <XCircle size={14} className="text-red-500" />}
          {status === 'canceled' && <Ban size={14} className="text-yellow-500" />}
          <span>任务进度</span>
          <span className={`text-xs ${statusColor}`}>· {statusLabel}</span>
          {activeProfile && (
            <span className="text-[10px] bg-gray-800 text-gray-400 px-1.5 py-0.5 rounded">
              @{activeProfile}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {canCancel && (
            <button
              onClick={handleCancel}
              disabled={canceling}
              className="p-1 hover:bg-gray-700 rounded text-yellow-400 disabled:opacity-40"
              title="取消任务"
            >
              {canceling ? <Loader2 size={14} className="animate-spin" /> : <Square size={14} />}
            </button>
          )}
          <button onClick={toggleMinimize} className="p-1 hover:bg-gray-700 rounded" title="收起到角落">
            <Minimize2 size={14} />
          </button>
          <button onClick={closeDrawer} className="p-1 hover:bg-gray-700 rounded" title="关闭">
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Structured progress panel */}
      <div className="px-4 py-3 border-b border-gray-700 space-y-3">
        {/* 当前阶段 */}
        {latestProgress && (
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <span className="text-gray-400">当前阶段</span>
              <span className="bg-blue-900/50 text-blue-300 px-2 py-0.5 rounded">
                {phaseChipText(latestProgress.phase)}
              </span>
            </div>
            {progressPercent !== null && (
              <span className="text-gray-400">
                {progressCurrent}/{progressTotal} ({progressPercent}%)
              </span>
            )}
          </div>
        )}
        {/* 总进度条 */}
        {progressPercent !== null && (
          <div className="h-1.5 bg-gray-700 rounded overflow-hidden">
            <div
              className={`h-full transition-all duration-300 ${
                status === 'error' ? 'bg-red-500' : 'bg-blue-500'
              }`}
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        )}
        {/* 行级计数 */}
        {totalRows > 0 ? (
          <div className="grid grid-cols-4 gap-2 text-xs">
            <div className="bg-gray-800 rounded px-2 py-1.5 text-center">
              <div className="text-green-400 text-sm font-semibold">{counts.done}</div>
              <div className="text-gray-500 text-[10px]">已完成</div>
            </div>
            <div className="bg-gray-800 rounded px-2 py-1.5 text-center">
              <div className={`text-sm font-semibold ${counts.error > 0 ? 'text-red-400' : 'text-gray-500'}`}>
                {counts.error}
              </div>
              <div className="text-gray-500 text-[10px]">失败</div>
            </div>
            <div className="bg-gray-800 rounded px-2 py-1.5 text-center">
              <div className={`text-sm font-semibold ${counts.running > 0 ? 'text-blue-400' : 'text-gray-500'}`}>
                {counts.running}
              </div>
              <div className="text-gray-500 text-[10px]">处理中</div>
            </div>
            <div className="bg-gray-800 rounded px-2 py-1.5 text-center">
              <div className="text-sm font-semibold text-gray-300">{counts.pending}</div>
              <div className="text-gray-500 text-[10px]">待处理</div>
            </div>
          </div>
        ) : !latestProgress ? (
          <div className="text-gray-500 text-xs text-center py-4 flex flex-col items-center gap-2">
            {!isTerminal && <Loader2 size={20} className="animate-spin text-blue-500/50" />}
            <span>{isTerminal ? '本次任务无可观测的行级进度' : '正在初始化任务流水线...'}</span>
          </div>
        ) : null}
      </div>

      {/* Collapsible log */}
      <div className="flex-1 flex flex-col min-h-0">
        <button
          onClick={() => setLogExpanded(v => !v)}
          className="flex items-center gap-1 px-4 py-2 text-xs text-gray-400 hover:bg-gray-800 transition-colors border-b border-gray-700"
        >
          {logExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <span>原始日志</span>
          <span className="text-gray-600">({logEvents.length})</span>
        </button>
        {logExpanded && (
          <div className="flex-1 overflow-y-auto px-3 py-2 text-xs font-mono space-y-0.5 max-h-[40vh]">
            {logEvents.length === 0 && (
              <div className="text-gray-500 py-4 text-center">暂无日志</div>
            )}
            {logEvents.map((e, i) => (
              <div
                key={i}
                className={`py-0.5 ${
                  e.level === 'error' ? 'text-red-400'
                  : e.level === 'warning' ? 'text-yellow-400'
                  : 'text-gray-300'
                }`}
              >
                <span className="text-gray-600 mr-2">
                  {e.ts ? new Date(e.ts * 1000).toLocaleTimeString('zh-CN', { hour12: false }) : ''}
                </span>
                {e.message}
              </div>
            ))}
            <div ref={logEndRef} />
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-2 border-t border-gray-700 text-xs text-gray-400">
        {isTerminal ? (
          <span>
            任务{statusLabel}
            {totalRows > 0 && (
              <>
                · 完成 <span className="text-green-400">{counts.done}</span>
                {counts.error > 0 && <> · 失败 <span className="text-red-400">{counts.error}</span></>}
                {counts.pending > 0 && <> · 未启动 {counts.pending}</>}
              </>
            )}
          </span>
        ) : (
          <span>任务进行中...</span>
        )}
        {cancelError && <div className="text-red-400 mt-1">{cancelError}</div>}
      </div>
    </div>
  )
}
