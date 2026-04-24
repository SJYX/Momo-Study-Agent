/**
 * components/tasks/TaskDrawer.tsx — 全局右下角悬浮任务面板。
 *
 * 订阅当前活跃任务的 SSE 事件流，渲染进度条和日志。
 */
import { useEffect, useRef } from 'react'
import { X, Minimize2, Loader2, CheckCircle2, XCircle, Ban, Square } from 'lucide-react'
import { useTaskStream } from '../../hooks/useTaskStream'
import { useTaskStore } from '../../stores/tasks'
import { apiPost } from '../../api/client'
import { useState } from 'react'

export default function TaskDrawer() {
  const { activeTaskId, drawerOpen, drawerMinimized, setTaskStatus, addEvent, closeDrawer, toggleMinimize } = useTaskStore()
  const logEndRef = useRef<HTMLDivElement>(null)
  const [canceling, setCanceling] = useState(false)
  const [cancelError, setCancelError] = useState('')

  const { events, status } = useTaskStream({
    taskId: activeTaskId,
    enabled: drawerOpen && !!activeTaskId,
    onEvent: (e) => addEvent(e),
    onDone: (s) => setTaskStatus(s),
  })

  useEffect(() => {
    setTaskStatus(status)
  }, [status]) // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll log
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events])

  if (!drawerOpen || !activeTaskId) return null

  const isTerminal = ['done', 'error', 'canceled'].includes(status)
  const canCancel = ['pending', 'running', 'connected', 'connecting'].includes(status)
  const logEvents = events.filter(e => e.type === 'log')
  const progressEvents = events.filter(e => e.type === 'log' && !!e.event)
  const latestProgress = progressEvents.length > 0 ? progressEvents[progressEvents.length - 1] : null
  const progressPayload = latestProgress?.progress
  const progressRecord = progressPayload && typeof progressPayload === 'object' ? (progressPayload as Record<string, unknown>) : null
  const progressCurrent = typeof progressRecord?.current === 'number' ? progressRecord.current : null
  const progressTotal = typeof progressRecord?.total === 'number' ? progressRecord.total : null
  const progressPercent = progressCurrent !== null && progressTotal ? Math.max(0, Math.min(100, Math.round((progressCurrent / progressTotal) * 100))) : null
  const statusColor = status === 'done' ? 'text-green-500' : status === 'error' ? 'text-red-500' : status === 'running' ? 'text-blue-500' : 'text-gray-400'

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
        <span className={statusColor}>{status}</span>
        <span className="text-gray-400">|</span>
        <span>{logEvents.length} 日志</span>
      </button>
    )
  }

  return (
    <div className="fixed bottom-4 right-4 w-[480px] max-h-[60vh] bg-gray-900 text-gray-100 rounded-lg shadow-2xl flex flex-col z-50 border border-gray-700">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-700">
        <div className="flex items-center gap-2 text-sm font-medium">
          {status === 'running' && <Loader2 size={14} className="animate-spin text-blue-500" />}
          {status === 'pending' && <Loader2 size={14} className="text-gray-400" />}
          {status === 'done' && <CheckCircle2 size={14} className="text-green-500" />}
          {status === 'error' && <XCircle size={14} className="text-red-500" />}
          {status === 'canceled' && <Ban size={14} className="text-yellow-500" />}
          <span>任务进度</span>
          <span className={`text-xs ${statusColor}`}>({status})</span>
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
          <button onClick={toggleMinimize} className="p-1 hover:bg-gray-700 rounded">
            <Minimize2 size={14} />
          </button>
          <button onClick={closeDrawer} className="p-1 hover:bg-gray-700 rounded">
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Log stream */}
      <div className="flex-1 overflow-y-auto px-3 py-2 text-xs font-mono space-y-0.5 min-h-[200px] max-h-[50vh]">
        {progressPercent !== null && (
          <div className="mb-3">
            <div className="flex items-center justify-between text-[11px] text-gray-400 mb-1">
              <span>结构化进度</span>
              <span>{progressCurrent}/{progressTotal} ({progressPercent}%)</span>
            </div>
            <div className="h-1.5 bg-gray-700 rounded overflow-hidden">
              <div className="h-full bg-blue-500 transition-all duration-300" style={{ width: `${progressPercent}%` }} />
            </div>
          </div>
        )}
        {logEvents.length === 0 && !isTerminal && (
          <div className="text-gray-500 py-8 text-center">等待日志输出...</div>
        )}
        {logEvents.map((e, i) => (
          <div key={i} className={`py-0.5 ${e.level === 'error' ? 'text-red-400' : e.level === 'warning' ? 'text-yellow-400' : 'text-gray-300'}`}>
            <span className="text-gray-600 mr-2">
              {e.ts ? new Date(e.ts * 1000).toLocaleTimeString('zh-CN', { hour12: false }) : ''}
            </span>
            {typeof e.message === 'string' ? e.message : String(e.message ?? '')}
          </div>
        ))}
        <div ref={logEndRef} />
      </div>

      {/* Footer */}
      <div className="px-4 py-2 border-t border-gray-700 text-xs text-gray-400">
        {isTerminal ? `任务已${status === 'done' ? '完成' : status === 'error' ? '出错' : '取消'}，共 ${logEvents.length} 条日志` : '任务进行中...'}
        {cancelError && <div className="text-red-400 mt-1">{cancelError}</div>}
      </div>
    </div>
  )
}
