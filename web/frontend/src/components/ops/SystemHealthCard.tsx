/**
 * components/ops/SystemHealthCard.tsx — Spec §3.3 系统健康卡。
 */
import { useState } from 'react'
import { Wifi, WifiOff, CheckCircle2, XCircle, ChevronDown } from 'lucide-react'
import type { PreflightCheck } from '../../api/types'

export default function SystemHealthCard({
  systemOk,
  checks,
}: {
  systemOk: boolean
  checks: PreflightCheck[]
}) {
  const [expanded, setExpanded] = useState(false)
  const visible = expanded ? checks : checks.slice(0, 5)

  return (
    <div className="bg-surface-card rounded-card shadow-card p-4">
      <div className="flex items-center gap-2 mb-3">
        {systemOk ? (
          <Wifi size={16} className="text-text-primary" />
        ) : (
          <WifiOff size={16} className="text-error" />
        )}
        <h3 className="text-sm font-semibold text-text-primary">系统健康</h3>
        <span className={`text-xs ml-auto ${systemOk ? 'text-text-muted' : 'text-error font-medium'}`}>
          {systemOk ? '正常' : '异常'}
        </span>
      </div>
      {checks.length === 0 ? (
        <div className="text-text-muted text-sm text-center py-6">暂无检查记录</div>
      ) : (
        <div className="space-y-1">
          {visible.map((c, i) => (
            <div key={i} className="flex items-center gap-2 text-sm py-1">
              {c.ok ? (
                <CheckCircle2 size={14} className="text-text-secondary" />
              ) : (
                <XCircle size={14} className="text-error" />
              )}
              <span className={c.ok ? 'text-text-secondary' : 'text-error font-medium'}>{c.name}</span>
              {!c.ok && <span className="text-xs text-text-muted truncate">{c.detail}</span>}
            </div>
          ))}
          {checks.length > 5 && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="text-xs text-text-muted hover:text-text-primary flex items-center gap-1 mt-1"
            >
              <ChevronDown size={12} className={expanded ? 'rotate-180' : ''} />
              {expanded ? '收起' : `展开全部 (${checks.length})`}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
