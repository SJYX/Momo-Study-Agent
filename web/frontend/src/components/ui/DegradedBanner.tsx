/**
 * components/ui/DegradedBanner.tsx — 性能降级提示原子。
 *
 * 与 ErrorBanner 形态相近但语义不同：
 * - ErrorBanner：硬错误，红色
 * - DegradedBanner：系统繁忙时主动降级返回轻量响应，黄色
 *
 * 触发条件由后端 API 在响应体中带 `degraded: true` 标记（PLAYBOOK A4 Kill Switch 通道）。
 * 非侵入式：仅当 active=true 时渲染，否则返回 null。
 */
import { AlertCircle } from 'lucide-react'

export interface DegradedBannerProps {
  /** 是否处于降级状态；false/undefined 不渲染。 */
  active?: boolean | null
  /** 用户可见的主提示文案。 */
  message?: string
  /** 后端给出的降级原因（如 flag 名），作为次级说明展示。 */
  reason?: string | null
  /** 自定义 mb 间距，默认 mb-4。 */
  mb?: 'mb-2' | 'mb-3' | 'mb-4' | 'mb-0'
}

export default function DegradedBanner({
  active,
  message = '系统繁忙，部分数据已降级展示',
  reason,
  mb = 'mb-4',
}: DegradedBannerProps) {
  if (!active) return null
  return (
    <div className={`bg-yellow-50 border-l-4 border-yellow-400 p-3 rounded ${mb} text-sm text-yellow-800 flex items-start gap-2`}>
      <AlertCircle size={16} className="mt-0.5 flex-shrink-0" />
      <div className="flex-1">
        <div className="font-medium">{message}</div>
        {reason && <div className="text-xs opacity-80 mt-0.5">原因：{reason}</div>}
      </div>
    </div>
  )
}
