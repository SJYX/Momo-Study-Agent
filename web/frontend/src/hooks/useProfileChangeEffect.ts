/**
 * hooks/useProfileChangeEffect.ts — profile 切换时清理任务状态。
 *
 * P0-T6: 切换 profile 时取消旧 SSE 连接，清空 TaskDrawer 状态。
 */
import { useEffect, useRef } from 'react'
import { useProfileStore } from '../stores/profile'
import { useTaskStore } from '../stores/tasks'

export function useProfileChangeEffect() {
  const activeProfile = useProfileStore((s) => s.activeProfile)
  const prevProfileRef = useRef(activeProfile)

  useEffect(() => {
    if (prevProfileRef.current !== activeProfile) {
      prevProfileRef.current = activeProfile
      // 清空任务状态（会触发 SSE 断开）
      useTaskStore.getState().reset()
    }
  }, [activeProfile])
}
