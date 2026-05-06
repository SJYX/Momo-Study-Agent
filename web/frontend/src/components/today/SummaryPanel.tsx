/**
 * components/today/SummaryPanel.tsx — 任务完成后的结果摘要面板。
 *
 * V1-T4（flag: ff_today_summary_stay）：
 *   - 终态时展示在列表上方
 *   - 包含成功/失败/跳过计数
 *   - 联动 T5 失败分组入口
 */
import { CheckCircle2, XCircle, Ban, AlertCircle, ArrowRight } from 'lucide-react'

export interface SummaryPanelProps {
  /** 成功（done）条目数 */
  doneCount: number
  /** 失败（error）条目数 */
  errorCount: number
  /** 跳过（skipped）条目数 */
  skippedCount: number
  /** 总条目数 */
  totalCount: number
  /** 任务终态类型：done / error / canceled */
  taskStatus: string
  /** 点击"进入失败分组"（联动 T5，T5 未完成时为 undefined） */
  onGoToFailures?: () => void
}

export default function SummaryPanel({
  doneCount,
  errorCount,
  skippedCount,
  totalCount,
  taskStatus,
  onGoToFailures,
}: SummaryPanelProps) {
  // 顶部状态条样式
  let headerConfig = {
    title: '任务完成',
    icon: <CheckCircle2 className="text-green-600" size={18} />,
    bg: 'bg-green-50',
    border: 'border-green-200',
    text: 'text-green-800'
  }
  
  if (taskStatus === 'error') {
    headerConfig = {
      title: '任务异常终止',
      icon: <AlertCircle className="text-red-600" size={18} />,
      bg: 'bg-red-50',
      border: 'border-red-200',
      text: 'text-red-800'
    }
  } else if (taskStatus === 'canceled') {
    headerConfig = {
      title: '任务已取消',
      icon: <Ban className="text-gray-600" size={18} />,
      bg: 'bg-gray-100',
      border: 'border-gray-300',
      text: 'text-gray-800'
    }
  }

  return (
    <div className={`mb-6 rounded-lg border ${headerConfig.border} bg-white overflow-hidden shadow-sm animate-in fade-in duration-300`}>
      {/* Header */}
      <div className={`flex items-center gap-2 px-4 py-3 ${headerConfig.bg} border-b ${headerConfig.border} ${headerConfig.text} font-medium`}>
        {headerConfig.icon}
        <span>{headerConfig.title}</span>
        <span className="ml-auto text-sm opacity-80">总计 {totalCount} 条</span>
      </div>

      {/* Stats */}
      <div className="p-4 grid grid-cols-3 gap-4">
        <div className="flex flex-col items-center p-3 bg-gray-50 rounded border border-gray-100">
          <span className="text-2xl font-semibold text-green-600">{doneCount}</span>
          <span className="text-xs text-gray-500 mt-1 flex items-center gap-1">
            <CheckCircle2 size={12} /> 成功
          </span>
        </div>
        <div className="flex flex-col items-center p-3 bg-gray-50 rounded border border-gray-100">
          <span className="text-2xl font-semibold text-red-600">{errorCount}</span>
          <span className="text-xs text-gray-500 mt-1 flex items-center gap-1">
            <XCircle size={12} /> 失败
          </span>
        </div>
        <div className="flex flex-col items-center p-3 bg-gray-50 rounded border border-gray-100">
          <span className="text-2xl font-semibold text-gray-600">{skippedCount}</span>
          <span className="text-xs text-gray-500 mt-1 flex items-center gap-1">
            <Ban size={12} /> 跳过
          </span>
        </div>
      </div>

      {/* Action Area */}
      <div className="px-4 py-3 bg-gray-50 border-t border-gray-100 flex justify-end">
        <button
          onClick={onGoToFailures}
          disabled={!onGoToFailures || errorCount === 0}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100 disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed transition-colors text-sm font-medium"
        >
          进入失败分组
          <ArrowRight size={14} />
        </button>
      </div>
    </div>
  )
}
