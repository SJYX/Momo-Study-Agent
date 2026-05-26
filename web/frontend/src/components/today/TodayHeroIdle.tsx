/**
 * components/today/TodayHeroIdle.tsx — Spec §4.2 ① Idle 状态。
 */
import RingChart from '../ui/RingChart'

export interface TodayHeroIdleProps {
  totalCount: number
  doneCount: number
  errorCount: number
  filteredCount: number
  filterView: string
  onStart: () => void
  disabled?: boolean
  onRetryFailures?: () => void
}

export default function TodayHeroIdle(props: TodayHeroIdleProps) {
  const percentage = props.totalCount > 0 ? (props.doneCount / props.totalCount) * 100 : 0
  const actionText = props.filterView === 'all' ? `处理剩余 (${Math.max(0, props.filteredCount - props.doneCount)})` : `处理选中视图 (${props.filteredCount})`

  return (
    <div className="bg-gradient-to-br from-surface-highlight to-surface-base rounded-card border border-border-hero shadow-hero p-5 mb-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <RingChart percentage={percentage} />
          <div>
            <h2 className="text-lg font-semibold text-text-primary">今日进度</h2>
            <p className="text-sm text-text-secondary mt-1">{props.doneCount} / {props.totalCount} 已完成</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {props.errorCount > 0 && props.onRetryFailures && (
            <button 
              onClick={props.onRetryFailures}
              disabled={props.disabled}
              className="bg-error-soft text-error px-4 py-2 rounded-button text-sm font-medium hover:bg-error/10 transition-colors"
            >
              ↻ 重试 {props.errorCount} 个失败
            </button>
          )}
          <button
            onClick={props.onStart}
            disabled={props.disabled || props.filteredCount === 0}
            className="bg-accent text-white px-4 py-2 rounded-button text-sm font-medium hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            🚀 {actionText}
          </button>
        </div>
      </div>
    </div>
  )
}
