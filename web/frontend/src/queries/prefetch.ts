/**
 * queries/prefetch.ts — Sidebar / 列表行 hover 时的预拉发器。
 *
 * 集中维护「路由 path → React Query prefetch」映射，避免 prefetch 逻辑散落到 Sidebar 与各组件。
 * staleTime 由 QueryClient 默认 30s 控制（queryClient.ts:17）——hover 两次自动防抖。
 *
 * 边界：
 * - 只为已经走 React Query 的页面 prefetch；FuturePlan / Iteration 仍是 useState/useEffect 模式，prefetch 无用，故跳过。
 * - 词库与 OpsMonitor 等带参数的 query 用默认参数 prefetch（page=1、window=1h 等）——首次进入命中率最高的状态。
 */
import type { QueryClient } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { activeProfile, queryKeys } from './queryClient'
import type {
  OpsStatsResponse,
  PreflightResponse,
  SessionInfo,
  StatsSummary,
  SyncStatusResponse,
  TodayItemsResponse,
  UsersListResponse,
  WordsListResponse,
} from '../api/types'

/** 触发指定路由对应的 prefetch；未注册的路由静默忽略。 */
export function prefetchForRoute(qc: QueryClient, path: string): void {
  const profile = activeProfile()

  switch (path) {
    case '/':
    case '/dashboard':
      void qc.prefetchQuery({
        queryKey: queryKeys.statsSummary(profile),
        queryFn: async () => {
          const r = await apiClient<StatsSummary>('/api/stats/summary')
          return r.data
        },
      })
      void qc.prefetchQuery({
        queryKey: queryKeys.session(),
        queryFn: async () => {
          const r = await apiClient<SessionInfo>('/api/session')
          return r.data
        },
      })
      // '/' 路由在 ff_ops_monitor 启用时落到 OpsMonitor — 同时预拉一份默认 window 的 ops 数据
      void qc.prefetchQuery({
        queryKey: queryKeys.opsMonitor(profile, '1h'),
        queryFn: async () => {
          const r = await apiClient<OpsStatsResponse>(
            `/api/stats/ops?profile=${encodeURIComponent(profile)}&window=1h`,
          )
          return r.data
        },
      })
      return

    case '/today':
      void qc.prefetchQuery({
        queryKey: queryKeys.today(profile),
        queryFn: async () => {
          const r = await apiClient<TodayItemsResponse>('/api/study/today')
          return r.data
        },
      })
      return

    case '/words':
      void qc.prefetchQuery({
        queryKey: queryKeys.wordLibrary(profile, 1, 30, '', null, null),
        queryFn: async () => {
          const r = await apiClient<WordsListResponse>('/api/words?page=1&page_size=30')
          return r.data
        },
      })
      return

    case '/sync':
      void qc.prefetchQuery({
        queryKey: queryKeys.syncStatus(profile),
        queryFn: async () => {
          const r = await apiClient<SyncStatusResponse>('/api/sync/status')
          return r.data
        },
      })
      return

    case '/preflight':
      void qc.prefetchQuery({
        queryKey: queryKeys.preflight(profile),
        queryFn: async () => {
          const r = await apiClient<PreflightResponse>('/api/preflight')
          return r.data
        },
      })
      return

    case '/users':
      void qc.prefetchQuery({
        queryKey: queryKeys.users(),
        queryFn: async () => {
          const r = await apiClient<UsersListResponse>('/api/users')
          return r.data
        },
      })
      return

    default:
      // /future, /iteration 仍是 useState/useEffect 模式，prefetch 不命中，跳过。
      return
  }
}
