export interface BottomBarProps {
  selectedCount: number
  onCancel: () => void
  onProcess: () => void
  disabled?: boolean
}

export default function BottomBar({ selectedCount, onCancel, onProcess, disabled }: BottomBarProps) {
  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 transform transition-transform duration-300 translate-y-0">
      <div className="bg-surface-card border-t border-border-default shadow-lg p-4 flex items-center justify-between max-w-5xl mx-auto rounded-t-xl">
        <div className="flex items-center gap-4">
          <span className="text-text-primary font-medium">已选择 {selectedCount} 个词</span>
          <button 
            onClick={onCancel}
            className="text-text-secondary hover:text-text-primary text-sm px-3 py-1.5 rounded-button hover:bg-surface-hover transition-colors"
          >
            取消选择
          </button>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={onProcess}
            disabled={disabled || selectedCount === 0}
            className="bg-accent text-white px-6 py-2 rounded-button text-sm font-medium hover:bg-accent-hover disabled:opacity-50 transition-colors shadow-sm"
          >
            🚀 处理选中项
          </button>
        </div>
      </div>
    </div>
  )
}
