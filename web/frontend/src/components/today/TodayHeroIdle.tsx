/**
 * components/today/TodayHeroIdle.tsx — Spec §4.2 ① Idle 状态。
 */
import { PlayCircle, Filter } from 'lucide-react'

export default function TodayHeroIdle({
  totalCount,
  executableCount,
  doneCount,
  showAll,
  onStart,
  onToggleShowAll,
  disabled,
}: {
  totalCount: number
  executableCount: number
  doneCount: number
  showAll: boolean
  onStart: () => void
  onToggleShowAll: () => void
  disabled?: boolean
}) {
  return (
    <div className="rounded-card border border-border-hero shadow-hero p-6 bg-gradient-to-br from-surface-card to-surface-highlight">
      <div className="text-xs text-text-muted mb-1">今日待处理 · 价值优先</div>
      <div className="text-3xl font-bold text-text-primary mb-2">{totalCount} 个单词</div>
      <div className="flex gap-3 text-sm text-text-secondary mb-4">
        <span><b className="text-text-primary">{executableCount}</b> 可执行</span>
        <span className="text-text-muted">·</span>
        <span><b className="text-text-primary">{doneCount}</b> 已完成</span>
      </div>
      <div className="flex gap-2">
        <button
          onClick={onStart}
          disabled={disabled || executableCount === 0}
          className="flex items-center gap-1.5 bg-accent hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed text-white px-5 py-2.5 rounded-button text-sm font-semibold transition-colors"
        >
          <PlayCircle size={16} />
          全部处理
        </button>
        <button
          onClick={onToggleShowAll}
          className="flex items-center gap-1.5 bg-accent-soft hover:bg-accent hover:text-white text-accent-hover px-4 py-2.5 rounded-button text-sm font-medium transition-colors"
        >
          <Filter size={14} />
          {showAll ? `仅可执行 (${executableCount})` : `查看全部 (${totalCount})`}
        </button>
      </div>
    </div>
  )
}
