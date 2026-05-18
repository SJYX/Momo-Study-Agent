/**
 * components/today/LightConfirmBar.tsx — 执行前轻确认条。
 *
 * V1-T2（flag: ff_today_light_confirm）：
 *   非弹窗、非 Modal 的内联横条。点击"全部处理"后展开，
 *   用户确认后才真正触发执行。
 *
 * 复用设计（T6b）：
 *   通过 message prop 可自定义文案（如"将重试 N 条"），
 *   缺省时使用默认文案"本次将执行 N 条，可随时停止"。
 */
import { Loader2, Play, X } from 'lucide-react'

export interface LightConfirmBarProps {
  /** 本次将执行的条目数量 */
  count: number
  /** 用户确认执行 */
  onConfirm: () => void
  /** 用户取消（收起确认条） */
  onCancel: () => void
  /** 是否正在执行中（确认后变为 loading 态） */
  loading?: boolean
  /** 自定义文案，缺省时使用默认文案 */
  message?: string
}

export default function LightConfirmBar({
  count,
  onConfirm,
  onCancel,
  loading = false,
  message,
}: LightConfirmBarProps) {
  // 兜底：count ≤ 0 时不渲染
  if (count <= 0) return null

  const displayMessage = message ?? `本次将执行 ${count} 条，可随时停止`

  return (
    <div
      className="flex items-center justify-between gap-3 px-4 py-3 mb-4 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-800 animate-in"
      style={{
        animation: 'slideDown 200ms ease-out',
      }}
    >
      <span className="flex-1">{displayMessage}</span>

      <div className="flex items-center gap-2 shrink-0">
        {loading ? (
          <span className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-blue-600 text-white text-xs opacity-70 cursor-not-allowed">
            <Loader2 size={14} className="animate-spin" />
            执行中…
          </span>
        ) : (
          <>
            <button
              onClick={onConfirm}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-blue-600 text-white text-xs hover:bg-blue-700 transition-colors"
            >
              <Play size={12} />
              确认执行
            </button>
            <button
              onClick={onCancel}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-blue-300 text-blue-700 text-xs hover:bg-blue-100 transition-colors"
            >
              <X size={12} />
              取消
            </button>
          </>
        )}
      </div>
    </div>
  )
}
