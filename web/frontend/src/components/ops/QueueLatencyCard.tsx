/**
 * components/ops/QueueLatencyCard.tsx — Spec §3.3 队列与延迟卡。
 */
import { Database } from 'lucide-react'
import type { OpsStatsResponse } from '../../api/types'

export default function QueueLatencyCard({ data }: { data: OpsStatsResponse | undefined }) {
  return (
    <div className="bg-surface-card rounded-card shadow-card p-4">
      <div className="flex items-center gap-2 mb-3">
        <Database size={16} className="text-text-primary" />
        <h3 className="text-sm font-semibold text-text-primary">队列与延迟</h3>
      </div>
      <div className="grid grid-cols-3 gap-3 mt-3">
        <Stat label="同步队列" value={data?.sync_queue_depth ?? 0} />
        <Stat label="冲突数" value={data?.sync_conflict_count ?? 0} accent={(data?.sync_conflict_count ?? 0) > 0} />
        <Stat label="平均延迟" value={`${data?.avg_latency_ms ?? 0}ms`} />
      </div>
    </div>
  )
}

function Stat({ label, value, accent }: { label: string; value: number | string; accent?: boolean }) {
  return (
    <div className="text-center">
      <div className={`text-xl font-bold ${accent ? 'text-error' : 'text-text-primary'}`}>{value}</div>
      <div className="text-[11px] text-text-muted">{label}</div>
    </div>
  )
}
