/**
 * hooks/useOpsPolling.ts — Ops Monitor 通用轮询 Hook。
 *
 * 支持：
 * - 可配置间隔（5s/10s/30s）
 * - 页面不可见时暂停
 * - 手动刷新
 * - 组件卸载时清理
 */
import { useCallback, useEffect, useRef, useState } from 'react'

interface UseOpsPollingOptions<T> {
  fetcher: () => Promise<T>
  intervalMs: number
  enabled?: boolean
}

export function useOpsPolling<T>({ fetcher, intervalMs, enabled = true }: UseOpsPollingOptions<T>) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const visibleRef = useRef(true)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const doFetch = useCallback(async () => {
    try {
      const result = await fetcherRef.current()
      setData(result)
      setError('')
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const refresh = useCallback(() => {
    setLoading(true)
    doFetch()
  }, [doFetch])

  useEffect(() => {
    if (!enabled) {
      doFetch()
      return
    }

    doFetch()

    const onVisibility = () => { visibleRef.current = !document.hidden }
    document.addEventListener('visibilitychange', onVisibility)

    const tick = () => {
      if (visibleRef.current) doFetch()
      timerRef.current = setTimeout(tick, intervalMs)
    }
    timerRef.current = setTimeout(tick, intervalMs)

    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [doFetch, intervalMs, enabled])

  return { data, loading, error, refresh, setData }
}
