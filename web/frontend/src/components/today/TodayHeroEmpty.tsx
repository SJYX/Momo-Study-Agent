/**
 * components/today/TodayHeroEmpty.tsx — Spec §4.2 ④ Empty 状态。
 */
import { useNavigate } from 'react-router-dom'

export default function TodayHeroEmpty() {
  const navigate = useNavigate()
  return (
    <div className="rounded-card border-2 border-dashed border-border-default p-8 bg-surface-card text-center">
      <div className="text-4xl mb-2">🎉</div>
      <div className="text-base font-semibold text-text-primary mb-1">今日已清空</div>
      <div className="text-sm text-text-muted mb-4">没有待处理的单词了。</div>
      <div className="flex gap-2 justify-center">
        <button
          onClick={() => navigate('/future')}
          className="bg-accent-soft hover:bg-accent hover:text-white text-accent-hover px-4 py-2 rounded-button text-sm font-medium transition-colors"
        >
          看未来计划 →
        </button>
        <button
          onClick={() => navigate('/iteration')}
          className="bg-accent-soft hover:bg-accent hover:text-white text-accent-hover px-4 py-2 rounded-button text-sm font-medium transition-colors"
        >
          智能迭代 →
        </button>
      </div>
    </div>
  )
}
