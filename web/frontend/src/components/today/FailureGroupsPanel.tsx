/**
 * components/today/FailureGroupsPanel.tsx
 *
 * V1-T5：失败分组视图。
 * - 接收构建好的分组数据并渲染。
 * - 支持手风琴折叠，默认展开第一组（失败数量最多）。
 * - 包含"重试本组"入口预留（T6b）。
 */
import { useState } from 'react'
import { ArrowLeft, ChevronDown, ChevronRight, AlertCircle, RotateCcw } from 'lucide-react'
import type { FailureGroup } from '../../utils/failureGrouping'
import { rowDisplayLabel, rowPhaseLabel } from '../../utils/rowProgress'
import type { RowState } from '../../utils/rowProgress'
import { isEnabled, BULK_RETRY_THRESHOLD } from '../../utils/featureFlags'
import LightConfirmBar from './LightConfirmBar'
import BulkGuardModal from './BulkGuardModal'

export interface FailureGroupsPanelProps {
  groups: FailureGroup[]
  rowStatusMap: Record<string, RowState>
  onRetryGroup?: (group: FailureGroup) => void // 预留给 T6b
  onBack: () => void
}

export default function FailureGroupsPanel({
  groups,
  rowStatusMap,
  onRetryGroup,
  onBack
}: FailureGroupsPanelProps) {
  // 默认展开第一个分组
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(
    new Set(groups.length > 0 ? [groups[0].groupKey] : [])
  )
  
  // 当前正在确认重试的分组
  const [confirmingGroup, setConfirmingGroup] = useState<string | null>(null)
  const [bulkConfirmingGroup, setBulkConfirmingGroup] = useState<string | null>(null)
  
  const bulkGuardEnabled = isEnabled('ff_today_bulk_guard')
  const residualHighlightEnabled = isEnabled('ff_today_residual_highlight')

  const toggleGroup = (key: string) => {
    setExpandedKeys(prev => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }

  return (
    <div className="bg-white rounded-lg shadow min-h-[400px] flex flex-col animate-in fade-in zoom-in-95 duration-200">
      {/* Header */}
      <div className="flex items-center gap-4 px-6 py-4 border-b border-gray-100">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-gray-500 hover:text-gray-900 transition-colors text-sm"
        >
          <ArrowLeft size={16} />
          返回完整列表
        </button>
        <h3 className="font-semibold text-gray-800 ml-2">失败分组处理</h3>
      </div>

      {/* Content */}
      <div className="p-6 flex-1 bg-gray-50/50">
        {groups.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            <AlertCircle className="mx-auto mb-2 opacity-50" size={32} />
            没有失败的条目
          </div>
        ) : (
          <div className="space-y-4">
            {groups.map((g) => {
              const isExpanded = expandedKeys.has(g.groupKey)
              return (
                <div key={g.groupKey} className="bg-white border border-gray-200 rounded-lg overflow-hidden shadow-sm">
                  {/* Group Header */}
                  <div
                    className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50 select-none"
                    onClick={() => toggleGroup(g.groupKey)}
                  >
                    <div className="text-gray-400 shrink-0">
                      {isExpanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                    </div>
                    
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-gray-800 truncate">{g.label}</span>
                        <span className="px-2 py-0.5 rounded-full bg-red-100 text-red-700 text-xs font-semibold">
                          {g.items.length}
                        </span>
                      </div>
                      <div className="text-xs text-gray-500 truncate mt-0.5 max-w-2xl">
                        {g.reason}
                      </div>
                    </div>

                    <div className="shrink-0 ml-4" onClick={e => e.stopPropagation()}>
                      <button
                        onClick={() => {
                          if (bulkGuardEnabled && g.items.length > BULK_RETRY_THRESHOLD) {
                            setBulkConfirmingGroup(g.groupKey)
                          } else {
                            setConfirmingGroup(g.groupKey)
                          }
                        }}
                        disabled={!onRetryGroup}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-white border border-gray-300 text-gray-700 text-sm hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        title={!onRetryGroup ? '此功能未开启(需 ff_today_group_retry)' : ''}
                      >
                        <RotateCcw size={14} />
                        重试本组
                      </button>
                    </div>
                  </div>

                  {/* Group Retry Confirm Bar */}
                  {confirmingGroup === g.groupKey && (
                    <div className="border-t border-gray-100 px-4 py-2 bg-blue-50/30">
                      <LightConfirmBar
                        count={g.items.length}
                        message={`将重试本组 ${g.items.length} 个单词`}
                        onConfirm={() => {
                          onRetryGroup?.(g)
                          setConfirmingGroup(null)
                        }}
                        onCancel={() => setConfirmingGroup(null)}
                      />
                    </div>
                  )}

                  {/* Bulk Guard Modal */}
                  {bulkConfirmingGroup === g.groupKey && (
                    <BulkGuardModal
                      count={g.items.length}
                      onConfirm={() => {
                        onRetryGroup?.(g)
                        setBulkConfirmingGroup(null)
                      }}
                      onCancel={() => setBulkConfirmingGroup(null)}
                    />
                  )}

                  {/* Group Items List */}
                  {isExpanded && (
                    <div className="border-t border-gray-100 bg-gray-50 p-4">
                      <table className="w-full text-sm">
                        <thead>
                          <tr>
                            <th className="text-left px-4 py-2 font-medium text-gray-500 text-xs w-12">#</th>
                            <th className="text-left px-4 py-2 font-medium text-gray-500 text-xs w-1/4">单词</th>
                            <th className="text-left px-4 py-2 font-medium text-gray-500 text-xs">进度状态</th>
                          </tr>
                        </thead>
                        <tbody>
                          {g.items.map((item, i) => {
                            const state = rowStatusMap[(item.voc_spelling || '').toLowerCase()]
                            const isResidualFailure = residualHighlightEnabled && state?.status === 'error'
                            return (
                              <tr 
                                key={item.voc_id} 
                                className={`border-t border-gray-100 transition-colors ${
                                  isResidualFailure ? 'bg-red-50/50 hover:bg-red-50 border-l-4 border-l-red-400' : 'hover:bg-white border-l-4 border-l-transparent'
                                }`}
                              >
                                <td className="px-4 py-2 text-gray-400">{i + 1}</td>
                                <td className="px-4 py-2 font-medium text-gray-700">{item.voc_spelling}</td>
                                <td className="px-4 py-2">
                                  <span
                                    className="text-xs px-2 py-1 rounded bg-red-50 text-red-700 border border-red-100"
                                    title={
                                      [
                                        rowPhaseLabel(state?.phase),
                                        state?.reason || '',
                                      ].filter(Boolean).join(' | ')
                                    }
                                  >
                                    {rowDisplayLabel(state)}
                                  </span>
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
