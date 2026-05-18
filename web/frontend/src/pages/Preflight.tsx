/**
 * pages/Preflight.tsx — 体检：一键运行 preflight 检查。
 *
 * React Query 改造：移除手写 useState<Data|null>/useState(loading)/useState(error)/useEffect+fetch
 * 模板，改为单个 useQuery + invalidate-on-active-user-changed。
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { useOnActiveUserChanged } from '../hooks/useOnActiveUserChanged'
import { queryKeys } from '../queries/queryClient'
import ErrorBanner from '../components/ui/ErrorBanner'
import type { PreflightResponse, PreflightCheck } from '../api/types'
import { Shield, CheckCircle2, XCircle, RefreshCw, Loader2 } from 'lucide-react'

export default function Preflight() {
  const queryClient = useQueryClient()
  const { data, error, isFetching, refetch } = useQuery({
    queryKey: queryKeys.preflight(),
    queryFn: async () => {
      const r = await apiClient<PreflightResponse>('/api/preflight')
      return r.data
    },
  })

  // 用户切换时让查询失效，下一次访问拉新数据
  useOnActiveUserChanged(() => {
    queryClient.invalidateQueries({ queryKey: ['preflight'] })
  })

  const checks = data?.checks ?? []
  const blockingCount = data?.blocking_items?.length ?? 0
  const errorMsg = error ? String(error instanceof Error ? error.message : error) : ''

  const StatusIcon = ({ check }: { check: PreflightCheck }) => {
    if (check.ok) return <CheckCircle2 size={16} className="text-green-500" />
    if (check.blocking) return <XCircle size={16} className="text-red-500" />
    return <XCircle size={16} className="text-yellow-500" />
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold">环境体检</h2>
          <p className="text-gray-500">
            {data ? (data.ok ? '✅ 所有检查通过' : '❌ 存在阻断项') : '加载中...'}
          </p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-2 px-3 py-1.5 border rounded text-sm hover:bg-gray-50 disabled:opacity-50"
        >
          {isFetching ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          重新检查
        </button>
      </div>

      <ErrorBanner message={errorMsg} />

      {data && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <div className={`px-4 py-3 border-b font-medium ${data.ok ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
            <Shield size={16} className="inline mr-2" />
            {data.ok ? '环境就绪' : `存在 ${blockingCount} 个阻断项`}
          </div>
          <div className="divide-y">
            {checks.map((check) => (
              <div key={check.name} className="px-4 py-3 flex items-start gap-3">
                <StatusIcon check={check} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm">{check.name}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded ${check.ok ? 'bg-green-100 text-green-700' : check.blocking ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'}`}>
                      {check.status}
                    </span>
                  </div>
                  <div className="text-sm text-gray-600 mt-0.5">{check.detail}</div>
                  {!check.ok && check.fix_hint && (
                    <div className="text-xs text-gray-400 mt-1">💡 {check.fix_hint}</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
