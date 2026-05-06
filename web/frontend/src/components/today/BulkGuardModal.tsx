import { AlertCircle, X } from 'lucide-react'

export interface BulkGuardModalProps {
  count: number
  onConfirm: () => void
  onCancel: () => void
}

export default function BulkGuardModal({ count, onConfirm, onCancel }: BulkGuardModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 animate-in fade-in duration-200">
      <div className="bg-white rounded-lg shadow-xl w-[400px] overflow-hidden animate-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 bg-red-50/50">
          <div className="flex items-center gap-2 text-red-600 font-medium">
            <AlertCircle size={18} />
            大批量重试确认
          </div>
          <button 
            onClick={onCancel}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 text-gray-700 text-sm">
          <p className="mb-2">
            注意：您即将重试 <span className="font-bold text-red-600">{count}</span> 个单词。
          </p>
          <p className="text-gray-500">
            大批量任务可能会消耗较多系统资源和等待时间。是否确认继续执行？
          </p>
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-gray-100 bg-gray-50 flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-gray-900 bg-white border border-gray-300 rounded hover:bg-gray-50 transition-colors"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded hover:bg-red-700 shadow-sm transition-colors"
          >
            确认重试
          </button>
        </div>
      </div>
    </div>
  )
}
