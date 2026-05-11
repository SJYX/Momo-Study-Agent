/**
 * components/ops/FailureHotspotsCard.tsx — Spec §3.3 失败热点卡。
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, XCircle, ChevronDown } from 'lucide-react'
import type { FailureHotspot } from '../../api/types'

function formatTimeAgo(ts: number): string {
  if (!ts) return '-'
  const diff = Date.now() / 1000 - ts
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  return `${Math.floor(diff / 86400)} 天前`
}

export default function FailureHotspotsCard({
  hotspots,
  timeWindow,
}: {
  hotspots: FailureHotspot[]
  timeWindow: string
}) {
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState(false)
  const visible = expanded ? hotspots : hotspots.slice(0, 5)

  return (
    <div className="bg-surface-card rounded-card shadow-card p-4">
      <div className="flex items-center gap-2 mb-3">
        <AlertTriangle size={16} className="text-error" />
        <h3 className="text-sm font-semibold text-text-primary">失败热点</h3>
      </div>
      {hotspots.length === 0 ? (
        <div className="text-text-muted text-sm text-center py-6">暂无失败记录</div>
      ) : (
        <div className="space-y-1">
          {visible.map((h, i) => (
            <div
              key={i}
              onClick={() =>
                navigate(
                  `/today?error_type=${encodeURIComponent(h.error_type)}&window=${encodeURIComponent(timeWindow)}`,
                )
              }
              className="flex items-center gap-2 text-sm py-1.5 px-2 rounded-pill hover:bg-surface-hover cursor-pointer"
            >
              <XCircle size={14} className="text-error" />
              <span className="font-medium text-text-primary">{h.error_type}</span>
              {h.error_code && <span className="text-xs text-text-muted">({h.error_code})</span>}
              <span className="text-xs text-text-muted ml-auto">{h.count} 次</span>
              <span className="text-xs text-text-muted">{formatTimeAgo(h.latest_at ?? 0)}</span>
            </div>
          ))}
          {hotspots.length > 5 && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="text-xs text-text-muted hover:text-text-primary flex items-center gap-1 mt-1"
            >
              <ChevronDown size={12} className={expanded ? 'rotate-180' : ''} />
              {expanded ? '收起' : `展开全部 (${hotspots.length})`}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
