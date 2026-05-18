/**
 * pages/OpsMonitorV2.tsx — OpsMonitor 重绘版本（Hero + 三卡）。
 * 数据层完全复用旧 OpsMonitor 的 useQuery；只换渲染。
 * Spec §3。
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, AlertTriangle, ChevronRight, Activity, PlayCircle } from 'lucide-react'
import { apiClient } from '../api/client'
import { useOnActiveUserChanged } from '../hooks/useOnActiveUserChanged'
import { useProfileStore } from '../stores/profile'
import { isEnabled } from '../utils/featureFlags'
import { queryKeys } from '../queries/queryClient'
import ErrorBanner from '../components/ui/ErrorBanner'
import OpsHero from '../components/ops/OpsHero'
import OpsSettingsPopover from '../components/ops/OpsSettingsPopover'
import FailureHotspotsCard from '../components/ops/FailureHotspotsCard'
import SystemHealthCard from '../components/ops/SystemHealthCard'
import QueueLatencyCard from '../components/ops/QueueLatencyCard'
import type { OpsStatsResponse } from '../api/types'

export default function OpsMonitorV2() {
  const queryClient = useQueryClient()
  const activeProfile = useProfileStore((s) => s.activeProfile)
  const navigate = useNavigate()

  const [pollInterval, setPollInterval] = useState(() => {
    try {
      return Number(localStorage.getItem('ops_poll_interval')) || 10000
    } catch {
      return 10000
    }
  })
  const [timeWindow, setTimeWindow] = useState(() => {
    try {
      return localStorage.getItem('ops_time_window') || '1h'
    } catch {
      return '1h'
    }
  })
  const [muted, setMuted] = useState(() => {
    try {
      return localStorage.getItem('ops_muted') === 'true'
    } catch {
      return false
    }
  })

  const pollingEnabled = isEnabled('ff_ops_monitor_polling')

  const { data, error, isFetching, refetch } = useQuery({
    queryKey: queryKeys.opsMonitor(activeProfile ?? '', timeWindow),
    queryFn: async () => {
      const res = await apiClient<OpsStatsResponse>(
        `/api/stats/ops?profile=${encodeURIComponent(activeProfile ?? '')}&window=${timeWindow}`,
      )
      return res.data
    },
    enabled: !!activeProfile,
    refetchInterval: pollingEnabled ? pollInterval : false,
    refetchIntervalInBackground: false,
  })

  useOnActiveUserChanged(() => {
    queryClient.invalidateQueries({ queryKey: ['ops_monitor'] })
  })

  const loading = isFetching && !data
  const errorMsg = error ? String(error instanceof Error ? error.message : error) : ''

  const updateTimeWindow = (v: string) => {
    setTimeWindow(v)
    try { localStorage.setItem('ops_time_window', v) } catch { /* ignore */ }
  }
  const updatePollInterval = (v: number) => {
    setPollInterval(v)
    try { localStorage.setItem('ops_poll_interval', String(v)) } catch { /* ignore */ }
  }
  const updateMuted = (v: boolean) => {
    setMuted(v)
    try { localStorage.setItem('ops_muted', String(v)) } catch { /* ignore */ }
  }

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center h-64 bg-surface-base">
        <RefreshCw size={20} className="animate-spin text-text-muted" />
        <span className="ml-2 text-text-secondary text-sm">加载监控数据...</span>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-4 bg-surface-base min-h-screen">
      {/* 告警条 */}
      {isEnabled('ff_ops_monitor_alert_bar') && data && !data.system_ok && (
        <div
          onClick={() => navigate('/preflight')}
          className="bg-error text-white px-4 py-2.5 rounded-button flex items-center justify-between cursor-pointer hover:bg-accent-hover transition-colors"
        >
          <div className="flex items-center gap-2">
            <AlertTriangle size={16} />
            <span className="text-sm font-medium">系统健康异常，点击查看详情</span>
          </div>
          <ChevronRight size={16} />
        </div>
      )}

      {/* Topbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Activity size={22} className="text-accent" />
          <div>
            <h2 className="text-xl font-bold text-text-primary">运维监控</h2>
            <p className="text-xs text-text-muted">{activeProfile ? `@${activeProfile}` : '加载中...'}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <OpsSettingsPopover
            timeWindow={timeWindow}
            onTimeWindowChange={updateTimeWindow}
            pollInterval={pollInterval}
            onPollIntervalChange={updatePollInterval}
            muted={muted}
            onMutedChange={updateMuted}
            data={data ?? undefined}
          />
          <button
            onClick={() => refetch()}
            className="p-2 rounded-button hover:bg-surface-hover transition-colors text-text-secondary"
            title="手动刷新"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <button
            onClick={() => navigate('/today')}
            className="flex items-center gap-1.5 bg-accent hover:bg-accent-hover text-white px-4 py-2 rounded-button text-sm font-semibold transition-colors"
          >
            <PlayCircle size={16} />
            进入今日执行
          </button>
        </div>
      </div>

      <ErrorBanner
        message={errorMsg}
        mb="mb-0"
        size="base"
        trailing={errorMsg ? <button onClick={() => refetch()} className="text-sm underline">重试</button> : undefined}
      />

      {/* Hero */}
      {!muted && <OpsHero data={data ?? undefined} timeWindow={timeWindow} />}

      {/* 三卡 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {!muted && <FailureHotspotsCard hotspots={data?.failure_hotspots ?? []} timeWindow={timeWindow} />}
        <SystemHealthCard systemOk={data?.system_ok !== false} checks={data?.health_checks ?? []} />
        {!muted && <QueueLatencyCard data={data ?? undefined} />}
      </div>
    </div>
  )
}
