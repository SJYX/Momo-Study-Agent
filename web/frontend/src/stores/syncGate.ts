/**
 * stores/syncGate.ts — Sync gate state.
 *
 * 当 backend 检测到当前 profile 的 DB 还在 init (pyturso 首次 bootstrap 可能 80-141s),
 * 业务 API 会返回 503 + `SYNCING`。此 store 记录该状态, 由 SyncGate 组件渲染遮罩 UI。
 *
 * 触发条件:
 *   - apiClient 收到 503 + SYNCING → setSyncing(true, profile)
 *   - useDbReady 轮询 /api/health/ready, ready=true 时 setSyncing(false)
 */
import { create } from 'zustand'

interface SyncGateState {
  // True 表示有 profile 的 DB 还在同步中, 业务 UI 应该被遮罩
  isSyncing: boolean
  // 正在同步的 profile (只记最近一次触发, 用于 UI 显示)
  syncingProfile: string | null
  setSyncing: (syncing: boolean, profile?: string | null) => void
}

export const useSyncGateStore = create<SyncGateState>((set) => ({
  isSyncing: false,
  syncingProfile: null,
  setSyncing: (syncing, profile = null) =>
    set({ isSyncing: syncing, syncingProfile: syncing ? profile : null }),
}))
