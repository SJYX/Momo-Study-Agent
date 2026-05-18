/**
 * hooks/useTaskStream.ts — SSE 事件流 Hook。
 *
 * 订阅 /api/tasks/{id}/events，实时接收任务进度事件。
 */
import { useEffect, useRef, useCallback, useState } from 'react'
import type { TaskEvent } from '../api/types'
import { apiClient } from '../api/client'

interface UseTaskStreamOptions {
  taskId: string | null
  enabled?: boolean
  onEvent?: (event: TaskEvent) => void
  onDone?: (finalStatus: string) => void
}

export function useTaskStream({ taskId, enabled = true, onEvent, onDone }: UseTaskStreamOptions) {
  const [events, setEvents] = useState<TaskEvent[]>([])
  const [status, setStatus] = useState<string>('idle')
  const esRef = useRef<EventSource | null>(null)

  const disconnect = useCallback(() => {
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!taskId || !enabled) {
      disconnect()
      return
    }

    const profile = sessionStorage.getItem('momo_active_profile') || ''
    if (!profile) {
      setStatus('error')
      return
    }

    setEvents([])
    setStatus('connecting')

    const url = `/api/tasks/${taskId}/events?profile=${encodeURIComponent(profile)}`
    const es = new EventSource(url)
    esRef.current = es

    es.onopen = () => setStatus('connected')

    // 监听 status 事件
    es.addEventListener('status', (e) => {
      try {
        const data: TaskEvent = JSON.parse(e.data)
        setEvents(prev => [...prev, data])
        if (data.type === 'status' && typeof data.status === 'string') {
          setStatus(data.status)
          onEvent?.(data)
          if (['done', 'error', 'canceled'].includes(data.status)) {
            onDone?.(data.status)
            es.close()
          }
        }
      } catch { /* ignore parse errors */ }
    })

    // 监听 log 事件
    es.addEventListener('log', (e) => {
      try {
        const data: TaskEvent = JSON.parse(e.data)
        setEvents(prev => [...prev, data])
        onEvent?.(data)
      } catch { /* ignore */ }
    })

    // 监听 progress 事件
    es.addEventListener('progress', (e) => {
      try {
        const data: TaskEvent = JSON.parse(e.data)
        setEvents(prev => [...prev, data])
        onEvent?.(data)
      } catch { /* ignore */ }
    })

    // 监听 row_status 事件
    es.addEventListener('row_status', (e) => {
      try {
        const data: TaskEvent = JSON.parse(e.data)
        setEvents(prev => [...prev, data])
        onEvent?.(data)
      } catch { /* ignore */ }
    })

    // 监听 message 事件（fallback）
    es.onmessage = (e) => {
      try {
        const data: TaskEvent = JSON.parse(e.data)
        setEvents(prev => [...prev, data])
        if (data.type === 'status' && typeof data.status === 'string') {
          setStatus(data.status)
          if (['done', 'error', 'canceled'].includes(data.status)) {
            onDone?.(data.status)
            es.close()
          }
        }
      } catch { /* ignore */ }
    }

    es.onerror = () => {
      setStatus('disconnected')
      es.close()
      // SSE 连接失败：可能是服务器重启导致旧 task 失效。
      // 通过 HTTP 检查任务状态，若不存在则调 onDone 解锁前端。
      apiClient(`/api/tasks/${taskId}?profile=${encodeURIComponent(profile)}`)
        .then(res => {
          if (!res.ok) {
            // 任务不存在（404）→ 标记 error 让前端恢复 idle
            onDone?.('error')
          }
          // 任务存在但 SSE 断了 → 状态留在 'disconnected'，用户可手动刷新
        })
        .catch(() => {
          // 网络不通 → 同样解锁，避免前端卡死
          onDone?.('error')
        })
    }

    return () => {
      disconnect()
    }
  }, [taskId, enabled]) // eslint-disable-line react-hooks/exhaustive-deps

  return { events, status, disconnect }
}
