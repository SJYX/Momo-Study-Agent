/**
 * components/today/DrillDownNotice.tsx — Spec §4.4 OpsMonitor drill-down 进入提示条。
 */
import { Filter, X } from 'lucide-react'

export default function DrillDownNotice({
  label,
  onClear,
}: {
  label: string
  onClear: () => void
}) {
  return (
    <div className="flex items-center gap-2 bg-accent-soft text-accent-hover px-3 py-2 rounded-button text-sm mt-3 mb-1">
      <Filter size={14} />
      <span>已应用筛选：<b>{label}</b></span>
      <button
        onClick={onClear}
        className="ml-auto text-accent-hover hover:text-accent-hover/80 p-1 rounded-pill hover:bg-accent-soft"
        title="清除筛选"
      >
        <X size={14} />
      </button>
    </div>
  )
}
