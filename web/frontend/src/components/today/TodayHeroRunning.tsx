/**
 * components/today/TodayHeroRunning.tsx — Spec §4.2 ② Running 状态。
 */
import { Square, Clock, Zap } from 'lucide-react'
import { useRunningElapsed, formatElapsed } from '../../hooks/useRunningElapsed'

export default function TodayHeroRunning({
  currentWord,
  phase,
  doneCount,
  runningCount,
  errorCount,
  pendingCount,
  totalCount,
  onCancel,
  disabled,
}: {
  currentWord: string | null
  phase: string | null
  doneCount: number
  runningCount: number
  errorCount: number
  pendingCount: number
  totalCount: number
  onCancel: () => void
  disabled?: boolean
}) {
  const elapsed = useRunningElapsed(true)
  const finished = doneCount + errorCount
  const progressPct = totalCount > 0 ? Math.round((finished / totalCount) * 100) : 0

  return (
    <div className="rounded-card border border-border-hero shadow-hero p-6 bg-gradient-to-br from-surface-card to-surface-highlight">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-text-muted">正在处理 ({finished}/{totalCount})</span>
        <span className="text-xs text-text-muted flex items-center gap-1">
          <Clock size={11} />
          已耗时 {formatElapsed(elapsed)}
        </span>
      </div>
      <div className="text-2xl font-bold text-text-primary mb-2">{currentWord || '准备中...'}</div>
      {phase && (
        <div className="flex items-center gap-1.5 text-sm text-accent mb-3">
          <Zap size={12} />
          {phase}
        </div>
      )}
      <div className="bg-border-default h-1.5 rounded-pill overflow-hidden mb-3">
        <div className="bg-accent h-full transition-all" style={{ width: `${progressPct}%` }} />
      </div>
      <div className="flex items-center justify-between">
        <div className="flex gap-4 text-xs">
          <Stat label="完成" value={doneCount} />
          <Stat label="运行" value={runningCount} color="text-accent" />
          <Stat label="错误" value={errorCount} color="text-error" />
          <Stat label="待" value={pendingCount} />
        </div>
        <button
          onClick={onCancel}
          disabled={disabled}
          className="flex items-center gap-1.5 bg-error hover:opacity-90 disabled:opacity-50 text-white px-4 py-2 rounded-button text-sm font-semibold transition-opacity"
        >
          <Square size={14} />
          停止处理
        </button>
      </div>
    </div>
  )
}

function Stat({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <span>
      <b className={`text-sm font-bold ${color || 'text-text-primary'}`}>{value}</b>
      <span className="text-text-muted ml-1">{label}</span>
    </span>
  )
}
