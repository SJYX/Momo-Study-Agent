/**
 * hooks/useDbReadyPoll.ts — 轮询 /api/health/ready, DB ready 时关闭 sync gate。
 *
 * 在 SyncGate 组件挂载时启动, 卸载时清理。
 * 默认每 2s 轮询一次。
 */
import { useEffect, useRef, useState } from 'react'
import { apiGet } from '../api/client'
import { useSyncGateStore } from '../stores/syncGate'

interface ReadyResponse {
  ready: boolean
  warmup_state: 'not_started' | 'db_init_in_progress' | 'db_init_done' | 'done'
  profile: string
}

export function useDbReadyPoll(enabled: boolean, intervalMs = 2000) {
  const [state, setState] = useState<ReadyResponse['warmup_state'] | 'unknown'>('unknown')
  const setSyncing = useSyncGateStore((s) => s.setSyncing)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!enabled) {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
      return
    }

    let cancelled = false

    const tick = async () => {
      try {
        const r = await apiGet<ReadyResponse>('/api/health/ready')
        if (cancelled || !r.data) return
        setState(r.data.warmup_state)
        if (r.data.ready) {
          // DB 已就绪, 关闭遮罩
          setSyncing(false)
          if (timerRef.current) {
            clearInterval(timerRef.current)
            timerRef.current = null
          }
        }
      } catch {
        // 网络抖动等忽略, 下一次再试
      }
    }

    // 立刻跑一次, 然后按 interval 轮询
    void tick()
    timerRef.current = setInterval(() => void tick(), intervalMs)

    return () => {
      cancelled = true
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
  }, [enabled, intervalMs, setSyncing])

  return state
}
