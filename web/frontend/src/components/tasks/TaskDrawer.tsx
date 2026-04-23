/**
 * components/tasks/TaskDrawer.tsx — 全局右下角悬浮任务面板。
 *
 * 订阅当前活跃任务的 SSE 事件流，渲染进度条和日志。
 */
import { useEffect, useRef } from 'react'
import { X, Minimize2, Loader2, CheckCircle2, XCircle, Ban } from 'lucide-react'
import { useTaskStream } from '../../hooks/useTaskStream'
import { useTaskStore } from '../../stores/tasks'

export default function TaskDrawer() {
  const { activeTaskId, drawerOpen, drawerMinimized, setTaskStatus, addEvent, closeDrawer, toggleMinimize } = useTaskStore()
  const logEndRef = useRef<HTMLDivElement>(null)

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
  const logEvents = events.filter(e => e.type === 'log')
  const statusColor = status === 'done' ? 'text-green-500' : status === 'error' ? 'text-red-500' : status === 'running' ? 'text-blue-500' : 'text-gray-400'

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
        {logEvents.length === 0 && !isTerminal && (
          <div className="text-gray-500 py-8 text-center">等待日志输出...</div>
        )}
        {logEvents.map((e, i) => (
          <div key={i} className={`py-0.5 ${e.level === 'error' ? 'text-red-400' : e.level === 'warning' ? 'text-yellow-400' : 'text-gray-300'}`}>
            <span className="text-gray-600 mr-2">
              {e.ts ? new Date(e.ts * 1000).toLocaleTimeString('zh-CN', { hour12: false }) : ''}
            </span>
            {e.message}
          </div>
        ))}
        <div ref={logEndRef} />
      </div>

      {/* Footer */}
      {isTerminal && (
        <div className="px-4 py-2 border-t border-gray-700 text-xs text-gray-400">
          任务已{status === 'done' ? '完成' : status === 'error' ? '出错' : '取消'}，共 {logEvents.length} 条日志
        </div>
      )}
    </div>
  )
}