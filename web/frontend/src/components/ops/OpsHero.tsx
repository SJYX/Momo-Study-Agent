/**
 * components/ops/OpsHero.tsx — OpsMonitor 顶部状态总览 Hero。
 * Spec §3.2。
 */
import { useNavigate } from 'react-router-dom'
import { Check, AlertTriangle, PlayCircle } from 'lucide-react'
import type { OpsStatsResponse } from '../../api/types'

const WINDOW_LABELS: Record<string, string> = {
  '15m': '最近 15 分钟',
  '1h': '最近 1 小时',
  '24h': '最近 24 小时',
}

export default function OpsHero({
  data,
  timeWindow,
}: {
  data: OpsStatsResponse | undefined
  timeWindow: string
}) {
  const navigate = useNavigate()
  const ok = data?.system_ok !== false
  const running = data?.tasks_running ?? 0
  const done = data?.tasks_done_1h ?? 0
  const errors = data?.tasks_error_1h ?? 0

  return (
    <div className="rounded-card border border-border-hero shadow-hero p-6 bg-gradient-to-br from-surface-card to-surface-highlight">
      <div className="text-xs text-text-muted mb-2">{WINDOW_LABELS[timeWindow] || timeWindow}</div>
      <div className="flex items-center gap-2 mb-4">
        {ok ? (
          <>
            <Check size={18} className="text-text-primary" />
            <span className="text-base font-semibold text-text-primary">全系统正常</span>
          </>
        ) : (
          <>
            <AlertTriangle size={18} className="text-error" />
            <span className="text-base font-semibold text-error">系统健康异常</span>
          </>
        )}
        <span className="text-xs text-text-muted ml-2">
          · {running} 项运行中 · {errors} 项错误
        </span>
      </div>
      <div className="flex items-center justify-between">
        <div className="flex gap-6">
          <Stat label="运行中" value={running} accent />
          <Stat label="已完成" value={done} />
          <Stat label="错误" value={errors} />
        </div>
        <button
          onClick={() => navigate('/today')}
          className="flex items-center gap-1.5 bg-accent hover:bg-accent-hover text-white px-4 py-2 rounded-button text-sm font-semibold transition-colors"
        >
          <PlayCircle size={16} />
          进入今日 →
        </button>
      </div>
    </div>
  )
}

function Stat({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div>
      <div className={`text-2xl font-bold ${accent ? 'text-accent' : 'text-text-primary'}`}>{value}</div>
      <div className="text-xs text-text-muted">{label}</div>
    </div>
  )
}
