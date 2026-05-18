/**
 * hooks/useRunningElapsed.ts — running 状态下的"已耗时（秒）"，每秒 tick。
 * 纯渲染装饰；不入 useTodayController。Spec §6。
 */
import { useEffect, useState } from 'react'

export function useRunningElapsed(isRunning: boolean): number {
  const [start, setStart] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (isRunning && start == null) {
      setStart(Date.now())
      setNow(Date.now())
    } else if (!isRunning && start != null) {
      setStart(null)
    }
  }, [isRunning, start])

  useEffect(() => {
    if (!isRunning) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [isRunning])

  return start ? Math.floor((now - start) / 1000) : 0
}

export function formatElapsed(sec: number): string {
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}m ${s}s`
}
