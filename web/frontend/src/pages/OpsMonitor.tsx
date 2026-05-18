/**
 * pages/OpsMonitor.tsx — 运维监控台（C05 Ops Monitor）。
 *
 * 默认首页，提供任务态势、失败热点、系统健康、队列深度四卡片。
 * 支持自动轮询 + 手动刷新 + 时间窗口切换 + 静音模式 + CSV 导出。
 *
 * React Query 改造：
 * - 用 useQuery 的 refetchInterval 替代手写 setTimeout 轮询
 * - 静音/可见性通过 enabled 与 refetchIntervalInBackground 控制
 * - 用户切换、时间窗口切换通过 queryKey 自然区分缓存
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity, RefreshCw, BellOff, Bell, Download, PlayCircle,
  Loader2, CheckCircle2, XCircle, Clock, AlertTriangle,
  Wifi, WifiOff, Database, ChevronDown, ChevronRight,
} from 'lucide-react'
import { apiClient } from '../api/client'
import { useOnActiveUserChanged } from '../hooks/useOnActiveUserChanged'
import { useProfileStore } from '../stores/profile'
import { isEnabled } from '../utils/featureFlags'
import { opsDataToCsv } from '../utils/opsCsv'
import { queryKeys } from '../queries/queryClient'
import ErrorBanner from '../components/ui/ErrorBanner'
import DbReplicaCard from '../components/ops/DbReplicaCard'
import type { OpsStatsResponse, TaskListItem, FailureHotspot, PreflightCheck } from '../api/types'
import OpsMonitorV2 from './OpsMonitorV2'

const POLL_INTERVALS = [
  { label: '5s', value: 5000 },
  { label: '10s', value: 10000 },
  { label: '30s', value: 30000 },
] as const

const TIME_WINDOWS = [
  { label: '15 分钟', value: '15m' },
  { label: '1 小时', value: '1h' },
  { label: '24 小时', value: '24h' },
] as const

const STATUS_ICONS: Record<string, typeof Activity> = {
  running: Loader2,
  done: CheckCircle2,
  error: XCircle,
  pending: Clock,
  canceled: AlertTriangle,
}

const STATUS_COLORS: Record<string, string> = {
  running: 'text-blue-500',
  done: 'text-green-500',
  error: 'text-red-500',
  pending: 'text-gray-400',
  canceled: 'text-yellow-500',
}

function formatTimeAgo(ts: number): string {
  if (!ts) return '-'
  const diff = Date.now() / 1000 - ts
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  return `${Math.floor(diff / 86400)} 天前`
}

function TaskTypeTag({ taskType }: { taskType: string }) {
  const labels: Record<string, string> = { today: '今日', future: '未来', iteration: '迭代' }
  const colors: Record<string, string> = {
    today: 'bg-blue-100 text-blue-700',
    future: 'bg-purple-100 text-purple-700',
    iteration: 'bg-orange-100 text-orange-700',
  }
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded ${colors[taskType] || 'bg-gray-100 text-gray-600'}`}>
      {labels[taskType] || taskType}
    </span>
  )
}

export default function OpsMonitor() {
  // eslint-disable-next-line react-hooks/rules-of-hooks
  if (isEnabled('ff_redesign_ops')) return <OpsMonitorV2 />

  const queryClient = useQueryClient()
  const activeProfile = useProfileStore(s => s.activeProfile)
  const navigate = useNavigate()

  const [pollInterval, setPollInterval] = useState(10000)
  const [timeWindow, setTimeWindow] = useState('1h')
  const [muted, setMuted] = useState(() => {
    try { return localStorage.getItem('ops_muted') === 'true' } catch { return false }
  })
  const [healthExpanded, setHealthExpanded] = useState(false)

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
    // 静音时仍拉取（数据要保鲜），只是 UI 不显示告警/卡片；
    // 不可见时由 refetchIntervalInBackground=false 自动停止。
    refetchInterval: pollingEnabled ? pollInterval : false,
    refetchIntervalInBackground: false,
  })

  useOnActiveUserChanged(() => {
    queryClient.invalidateQueries({ queryKey: ['ops_monitor'] })
  })

  const loading = isFetching && !data
  const errorMsg = error ? String(error instanceof Error ? error.message : error) : ''

  const fetchData = () => refetch()

  const toggleMute = () => {
    setMuted(v => {
      const next = !v
      try { localStorage.setItem('ops_muted', String(next)) } catch { /* ignore */ }
      return next
    })
  }

  const handleExportCsv = () => {
    if (!data) return
    const csv = opsDataToCsv(data)
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `ops-monitor-${new Date().toISOString().slice(0, 19)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleDrillDown = (task: TaskListItem) => {
    const path = task.task_type === 'future' ? '/future'
      : task.task_type === 'iteration' ? '/iteration'
      : '/today'
    navigate(path)
  }

  const handleHotspotDrillDown = (hotspot: FailureHotspot) => {
    navigate(`/today?error_type=${encodeURIComponent(hotspot.error_type)}&window=${timeWindow}`)
  }

  if (loading && !data) {
    return (
      <div className="p-6 flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-gray-400" size={24} />
        <span className="ml-2 text-gray-500">加载监控数据...</span>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-4">
      {/* 告警条 */}
      {isEnabled('ff_ops_monitor_alert_bar') && data && !data.system_ok && (
        <div
          className="bg-red-600 text-white px-4 py-2.5 rounded-lg flex items-center justify-between cursor-pointer hover:bg-red-700 transition-colors"
          onClick={() => navigate('/preflight')}
        >
          <div className="flex items-center gap-2">
            <AlertTriangle size={16} />
            <span className="text-sm font-medium">系统健康异常，点击查看详情</span>
          </div>
          <ChevronRight size={16} />
        </div>
      )}

      {/* 顶部栏 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Activity size={24} className="text-blue-600" />
          <div>
            <h2 className="text-2xl font-bold">运维监控</h2>
            <p className="text-sm text-gray-500">{activeProfile ? `@${activeProfile}` : '加载中...'}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* 时间窗口 */}
          <select
            value={timeWindow}
            onChange={e => setTimeWindow(e.target.value)}
            className="text-sm border rounded px-2 py-1 bg-white"
          >
            {TIME_WINDOWS.map(tw => (
              <option key={tw.value} value={tw.value}>{tw.label}</option>
            ))}
          </select>

          {/* 轮询间隔 */}
          {isEnabled('ff_ops_monitor_polling') && (
            <select
              value={pollInterval}
              onChange={e => setPollInterval(Number(e.target.value))}
              className="text-sm border rounded px-2 py-1 bg-white"
            >
              {POLL_INTERVALS.map(pi => (
                <option key={pi.value} value={pi.value}>{pi.label}</option>
              ))}
            </select>
          )}

          {/* 手动刷新 */}
          <button
            onClick={fetchData}
            className="p-2 rounded hover:bg-gray-100 transition-colors"
            title="手动刷新"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>

          {/* 静音 */}
          <button
            onClick={toggleMute}
            className="p-2 rounded hover:bg-gray-100 transition-colors"
            title={muted ? '取消静音' : '静音模式'}
          >
            {muted ? <BellOff size={16} className="text-gray-400" /> : <Bell size={16} />}
          </button>

          {/* CSV 导出 */}
          {isEnabled('ff_ops_monitor_csv_export') && (
            <button
              onClick={handleExportCsv}
              className="p-2 rounded hover:bg-gray-100 transition-colors"
              title="导出 CSV"
            >
              <Download size={16} />
            </button>
          )}

          {/* CTA */}
          <button
            onClick={() => navigate('/today')}
            className="flex items-center gap-1.5 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors"
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
        trailing={errorMsg ? <button onClick={fetchData} className="text-sm underline">重试</button> : undefined}
      />

      {/* 五卡片网格 */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {/* 卡片1：任务态势 */}
        {!muted && (
          <Card title="任务态势" icon={<Activity size={16} />}>
            <div className="grid grid-cols-3 gap-3 mb-3">
              <StatBox label="运行中" value={data?.tasks_running ?? 0} color="text-blue-600" />
              <StatBox label="近完成" value={data?.tasks_done_1h ?? 0} color="text-green-600" />
              <StatBox label="近错误" value={data?.tasks_error_1h ?? 0} color="text-red-600" />
            </div>
            <TaskList tasks={data?.recent_tasks ?? []} onDrillDown={handleDrillDown} />
          </Card>
        )}

        {/* 卡片2：失败热点 */}
        {!muted && (
          <Card title="失败热点" icon={<AlertTriangle size={16} />}>
            {(data?.failure_hotspots ?? []).length === 0 ? (
              <EmptyState text="暂无失败记录" />
            ) : (
              <div className="space-y-1.5">
                {(data?.failure_hotspots ?? []).map((h, i) => (
                  <HotspotRow key={i} hotspot={h} onClick={() => handleHotspotDrillDown(h)} />
                ))}
              </div>
            )}
          </Card>
        )}

        {/* 卡片3：系统健康 */}
        <Card title="系统健康" icon={data?.system_ok ? <Wifi size={16} className="text-green-500" /> : <WifiOff size={16} className="text-red-500" />}>
          <div className="flex items-center gap-2 mb-2">
            <span className={`text-sm font-medium ${data?.system_ok ? 'text-green-600' : 'text-red-600'}`}>
              {data?.system_ok ? '正常' : '异常'}
            </span>
          </div>
          {(data?.health_checks ?? []).length > 0 && (
            <div className="space-y-1">
              {(data?.health_checks ?? []).slice(0, healthExpanded ? undefined : 5).map((c, i) => (
                <HealthCheckRow key={i} check={c} />
              ))}
              {(data?.health_checks ?? []).length > 5 && (
                <button
                  onClick={() => setHealthExpanded(v => !v)}
                  className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
                >
                  {healthExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  {healthExpanded ? '收起' : `展开全部 (${data?.health_checks?.length})`}
                </button>
              )}
            </div>
          )}
        </Card>

        {/* 卡片4：队列深度 */}
        {!muted && (
          <Card title="队列与延迟" icon={<Database size={16} />}>
            <div className="grid grid-cols-3 gap-3">
              <StatBox label="同步队列" value={data?.sync_queue_depth ?? 0} color="text-yellow-600" />
              <StatBox label="冲突数" value={data?.sync_conflict_count ?? 0} color="text-red-600" />
              <StatBox label="平均延迟" value={`${data?.avg_latency_ms ?? 0}ms`} color="text-gray-600" />
            </div>
          </Card>
        )}

        {/* 卡片5：DB 副本健康 */}
        <DbReplicaCard profile={activeProfile ?? ''} />
      </div>
    </div>
  )
}

/* ---------- 子组件 ---------- */

function Card({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-lg shadow p-4">
      <div className="flex items-center gap-2 mb-3">
        {icon}
        <h3 className="font-medium text-sm">{title}</h3>
      </div>
      {children}
    </div>
  )
}

function StatBox({ label, value, color }: { label: string; value: number | string; color: string }) {
  return (
    <div className="text-center">
      <div className={`text-xl font-bold ${color}`}>{value}</div>
      <div className="text-[11px] text-gray-500">{label}</div>
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return <div className="text-gray-400 text-sm text-center py-6">{text}</div>
}

function TaskList({ tasks, onDrillDown }: { tasks: TaskListItem[]; onDrillDown: (t: TaskListItem) => void }) {
  if (tasks.length === 0) return <EmptyState text="暂无任务记录" />
  return (
    <div className="space-y-1">
      {tasks.map(t => {
        const Icon = STATUS_ICONS[t.status ?? ''] ?? Clock
        const color = STATUS_COLORS[t.status ?? ''] ?? 'text-gray-400'
        return (
          <div
            key={t.task_id}
            className="flex items-center gap-2 text-sm py-1 px-2 rounded hover:bg-gray-50 cursor-pointer"
            onClick={() => onDrillDown(t)}
          >
            <Icon size={14} className={color} />
            <TaskTypeTag taskType={t.task_type ?? 'today'} />
            <span className={`text-xs ${color}`}>{t.status}</span>
            <span className="text-xs text-gray-400 ml-auto">{formatTimeAgo(t.created_at ?? 0)}</span>
          </div>
        )
      })}
    </div>
  )
}

function HotspotRow({ hotspot, onClick }: { hotspot: FailureHotspot; onClick: () => void }) {
  return (
    <div
      className="flex items-center gap-2 text-sm py-1.5 px-2 rounded hover:bg-red-50 cursor-pointer"
      onClick={onClick}
    >
      <XCircle size={14} className="text-red-500" />
      <span className="font-medium text-red-700">{hotspot.error_type}</span>
      {hotspot.error_code && <span className="text-xs text-gray-500">({hotspot.error_code})</span>}
      <span className="text-xs text-gray-400 ml-auto">{hotspot.count} 次</span>
      <span className="text-xs text-gray-400">{formatTimeAgo(hotspot.latest_at ?? 0)}</span>
    </div>
  )
}

function HealthCheckRow({ check }: { check: PreflightCheck }) {
  return (
    <div className="flex items-center gap-2 text-sm py-1">
      {check.ok ? (
        <CheckCircle2 size={14} className="text-green-500" />
      ) : (
        <XCircle size={14} className="text-red-500" />
      )}
      <span className={check.ok ? 'text-gray-700' : 'text-red-700 font-medium'}>{check.name}</span>
      {!check.ok && <span className="text-xs text-gray-500 truncate">{check.detail}</span>}
    </div>
  )
}
