/**
 * components/ui/ErrorBanner.tsx — 错误提示横幅原子组件。
 *
 * 替代各页面里重复 9+ 次的：
 *   <div className="bg-red-50 text-red-700 p-3 rounded mb-4 text-sm">{errorMsg}</div>
 *
 * 仅在条件成立时渲染——传入空字符串/null/undefined 自动隐藏，调用方不必再写 `{err && ...}`。
 */
import { type ReactNode } from 'react'

export interface ErrorBannerProps {
  /** 错误内容，falsy 时不渲染。 */
  message?: string | null
  /** 文字大小，默认 sm。 */
  size?: 'sm' | 'base'
  /** 自定义 mb 间距，默认 mb-4。 */
  mb?: 'mb-2' | 'mb-3' | 'mb-4' | 'mb-0'
  /** 右侧附加节点，比如重试按钮。 */
  trailing?: ReactNode
}

export default function ErrorBanner({
  message,
  size = 'sm',
  mb = 'mb-4',
  trailing,
}: ErrorBannerProps) {
  if (!message) return null
  const text = size === 'sm' ? 'text-sm' : ''
  return (
    <div className={`bg-red-50 text-red-700 p-3 rounded ${mb} ${text} ${trailing ? 'flex items-center justify-between' : ''}`}>
      <span className="break-all">{message}</span>
      {trailing}
    </div>
  )
}
