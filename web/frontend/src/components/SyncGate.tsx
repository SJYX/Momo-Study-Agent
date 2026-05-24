/**
 * components/SyncGate.tsx — 首次 bootstrap 等待遮罩。
 *
 * 当 useSyncGateStore.isSyncing === true 时, 全屏覆盖一个加载遮罩,
 * 同时轮询 /api/health/ready, ready 后自动消失。
 *
 * 触发场景: pyturso 首次从云端 bootstrap 大数据库 (asher 用户 ~10MB 需要 80-141s)。
 * 期间业务 API 全部返回 503 + SYNCING, apiClient 自动 set isSyncing(true), 显示本组件。
 */
import { useSyncGateStore } from '../stores/syncGate'
import { useDbReadyPoll } from '../hooks/useDbReadyPoll'
import { useEffect, useState } from 'react'

const POLL_INTERVAL_MS = 400

export default function SyncGate() {
  const isSyncing = useSyncGateStore((s) => s.isSyncing)
  const profile = useSyncGateStore((s) => s.syncingProfile)
  const warmupState = useDbReadyPoll(isSyncing, POLL_INTERVAL_MS)
  const [elapsedSec, setElapsedSec] = useState(0)

  // 简单计时器, 给用户一个"已经等了多久"的反馈
  useEffect(() => {
    if (!isSyncing) {
      setElapsedSec(0)
      return
    }
    const startedAt = Date.now()
    const id = setInterval(() => {
      setElapsedSec(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    return () => clearInterval(id)
  }, [isSyncing])

  if (!isSyncing) return null

  const progressHint =
    warmupState === 'db_init_in_progress'
      ? '后台正在拉取云端数据...'
      : warmupState === 'db_init_done' || warmupState === 'done'
      ? '即将完成, 准备加载界面...'
      : '正在连接云端数据库...'

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="首次同步学习数据"
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm"
    >
      <div className="mx-4 max-w-md rounded-xl bg-white p-6 shadow-2xl">
        <div className="flex items-center gap-4">
          <div className="h-10 w-10 flex-shrink-0 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-lg font-semibold text-gray-800">
              正在首次同步学习数据
            </h3>
            {profile && (
              <p className="mt-0.5 text-sm text-gray-500">
                用户: <span className="font-mono">{profile}</span>
              </p>
            )}
          </div>
        </div>
        <p className="mt-4 text-sm text-gray-600">{progressHint}</p>
        <p className="mt-1 text-xs text-gray-400">
          首次启动通常需要 1-3 分钟从云端拉取全部数据, 之后再启动就秒回了。
        </p>
        <div className="mt-3 flex items-center justify-between text-xs text-gray-400">
          <span>状态: {warmupState}</span>
          <span>已等待 {elapsedSec}s</span>
        </div>
      </div>
    </div>
  )
}
