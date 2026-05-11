/**
 * components/today/TodayHeroDone.tsx — Spec §4.2 ③ Done 状态（决策 Z：不变色）。
 */
import { Check, RotateCw } from 'lucide-react'

export default function TodayHeroDone({
  doneCount,
  errorCount,
  skippedCount,
  totalCount,
  onViewFailures,
  onRetryBatch,
}: {
  doneCount: number
  errorCount: number
  skippedCount: number
  totalCount: number
  onViewFailures?: () => void
  onRetryBatch: () => void
}) {
  const successRate = totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0
  return (
    <div className="rounded-card border border-border-hero shadow-hero p-6 bg-gradient-to-br from-surface-card to-surface-highlight">
      <div className="flex items-center gap-2 mb-2">
        <Check size={16} className="text-text-primary" />
        <span className="text-xs text-text-muted">处理完成</span>
      </div>
      <div className="text-2xl font-bold text-text-primary mb-2">
        {doneCount} 成功 · {errorCount} 失败 · {skippedCount} 跳过
      </div>
      <div className="text-sm text-text-secondary mb-4">
        <span><b className="text-text-primary">{successRate}%</b> 成功率</span>
      </div>
      <div className="flex gap-2">
        {errorCount > 0 && onViewFailures && (
          <button
            onClick={onViewFailures}
            className="flex items-center gap-1.5 bg-error hover:opacity-90 text-white px-4 py-2.5 rounded-button text-sm font-semibold transition-opacity"
          >
            查看失败 ({errorCount}) →
          </button>
        )}
        <button
          onClick={onRetryBatch}
          className="flex items-center gap-1.5 bg-accent-soft hover:bg-accent hover:text-white text-accent-hover px-4 py-2.5 rounded-button text-sm font-medium transition-colors"
        >
          <RotateCw size={14} />
          再来一批
        </button>
      </div>
    </div>
  )
}
