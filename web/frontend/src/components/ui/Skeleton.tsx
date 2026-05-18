/**
 * components/ui/Skeleton.tsx — 骨架屏原子组件。
 *
 * 在数据加载完成前显示形态占位，替代裸 "加载中..." 文字。
 * 三个变体：
 * - SkeletonLine：单行占位（默认 h-4，可调宽度）
 * - SkeletonCard：Dashboard 单卡片占位（icon block + 两行文本）
 * - SkeletonRow：表格行占位（cols 列数）
 *
 * 所有变体使用 Tailwind 的 animate-pulse 实现脉动效果，无需自定义动画。
 */

interface SkeletonLineProps {
  /** Tailwind 宽度 class，默认 w-full。 */
  width?: string
  /** Tailwind 高度 class，默认 h-4。 */
  height?: string
  className?: string
}

export function SkeletonLine({ width = 'w-full', height = 'h-4', className = '' }: SkeletonLineProps) {
  return <div className={`${width} ${height} bg-gray-200 rounded animate-pulse ${className}`} />
}

export function SkeletonCard() {
  return (
    <div className="bg-white rounded-lg shadow p-4 flex items-center gap-4">
      <div className="bg-gray-200 w-11 h-11 rounded-lg animate-pulse" />
      <div className="flex-1 space-y-2">
        <SkeletonLine width="w-16" height="h-6" />
        <SkeletonLine width="w-24" height="h-3" />
      </div>
    </div>
  )
}

interface SkeletonRowProps {
  /** 表格列数。 */
  cols: number
}

export function SkeletonRow({ cols }: SkeletonRowProps) {
  return (
    <tr className="border-t">
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <SkeletonLine width={i === 0 ? 'w-24' : 'w-full'} />
        </td>
      ))}
    </tr>
  )
}
