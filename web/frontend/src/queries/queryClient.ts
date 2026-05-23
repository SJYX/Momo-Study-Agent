/**
 * queries/queryClient.ts — React Query 全局配置 + 查询键工厂。
 *
 * 设计要点：
 * - QueryClient 默认配置：staleTime 30s（页面切换不疯狂请求）、retry 1（避免业务错连环重试）、
 *   refetchOnWindowFocus false（与既有 useOnActiveUserChanged 不冲突）。
 * - queryKeys：集中维护查询键，按 [domain, ...args] 命名；profile 作为隐式作用域参与 key，
 *   保证用户切换后 cache 自然分离。
 * - apiClient 已在 !ok / HTTP error 时 throw Error，React Query 默认 error 处理直接生效，
 *   不需要额外的 wrapper。
 */
import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: 0,
    },
  },
})

/**
 * 当前活跃 profile（key 作用域）。
 * 用 sessionStorage 与 apiClient 的 X-Momo-Profile header 保持同源，
 * 切换用户时窗口分发 'active-user-changed' 事件，调用方负责 invalidate。
 */
export function activeProfile(): string {
  return sessionStorage.getItem('momo_active_profile') || ''
}

/**
 * 查询键工厂。所有 useQuery 必须从这里取 key，禁止裸字符串数组散落。
 */
export const queryKeys = {
  preflight: (profile: string = activeProfile()) =>
    ['preflight', profile] as const,
  syncStatus: (profile: string = activeProfile()) =>
    ['sync_status', profile] as const,
  today: (profile: string = activeProfile()) =>
    ['today', profile] as const,
  users: () => ['users'] as const,
  wordLibrary: (
    profile: string,
    page: number,
    pageSize: number,
    search?: string,
    syncStatusFilter?: number | null,
    itLevelFilter?: number | null,
  ) => ['word_library', profile, page, pageSize, search ?? '', syncStatusFilter, itLevelFilter] as const,
  wordDetail: (profile: string, vocId: string) =>
    ['word_detail', profile, vocId] as const,
  userGateway: () => ['user_gateway'] as const,
  opsMonitor: (profile: string, window: string) =>
    ['ops_monitor', profile, window] as const,
  statsSummary: (profile: string = activeProfile()) =>
    ['stats_summary', profile] as const,
  dbSyncHealth: (profile: string = activeProfile()) =>
    ['db_sync_health', profile] as const,
  session: () => ['session'] as const,
} as const
