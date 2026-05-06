import type { TodayItem } from '../api/types'
import type { RowState } from './rowProgress'

export interface FailureGroup {
  /** 分组唯一标识（type:XXX, code:XXX, 或 phase:XXX） */
  groupKey: string
  /** 友好的展示名（例如"网络异常"、"生成失败"） */
  label: string
  /** 代表性的错误原因摘要 */
  reason: string
  /** 属于该组的单词条目 */
  items: TodayItem[]
}

/**
 * 提取 items 中状态为 error 的项，并按 error_type -> error_code -> phase 进行分组。
 * 结果数组按 group 内 items 数量降序排列。
 */
export function buildFailureGroups(
  items: TodayItem[],
  rowStatusMap: Record<string, RowState>
): FailureGroup[] {
  const groupsMap = new Map<string, FailureGroup>()

  for (const item of items) {
    const key = (item.voc_spelling || '').toLowerCase()
    const state = rowStatusMap[key]

    // 只处理 error 状态的项
    if (!state || state.status !== 'error') {
      continue
    }

    // 1. 确定 groupKey
    let groupKey = ''
    let label = ''

    if (state.error_type) {
      groupKey = `type:${state.error_type}`
      label = `错误类型: ${state.error_type}`
    } else if (state.error_code) {
      groupKey = `code:${state.error_code}`
      label = `错误码: ${state.error_code}`
    } else if (state.phase) {
      groupKey = `phase:${state.phase}`
      label = `阶段失败: ${state.phase}`
    } else {
      groupKey = 'phase:unknown'
      label = '未知错误'
    }

    // 2. 获取或初始化 Group
    let group = groupsMap.get(groupKey)
    if (!group) {
      group = {
        groupKey,
        label,
        reason: state.reason || '未知错误',
        items: []
      }
      groupsMap.set(groupKey, group)
    }

    // 3. 加入项
    group.items.push(item)
  }

  // 4. 转数组并按 items 数量降序排序
  const sortedGroups = Array.from(groupsMap.values()).sort(
    (a, b) => b.items.length - a.items.length
  )

  return sortedGroups
}
