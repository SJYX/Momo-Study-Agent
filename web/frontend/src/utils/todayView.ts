/**
 * utils/todayView.ts — Today 列表的筛选/排序/跟随纯函数。
 *
 * 全部为纯函数，便于 vitest 单测；不依赖 DOM 或 window。
 *
 * V1 近似声明（见 V1_TASK_LIST.md §3）：
 *   - 价值优先：familiarity_short ASC（短期熟悉度低 = 需要更多练习 = 价值高）
 *   - 时间压力次级：review_count DESC（历史复习次数多 = 长期挂账压力大）
 *   - "可执行项"：phase != 'skipped' && status != 'done'
 *
 * 正式契约升级（引入 value_score 与 executable 字段）排到 C08。
 */
import type { TodayItem } from '../api/types'
import type { RowState } from './rowProgress'

/**
 * 按价值优先 + 时间压力次级排序。不修改入参。
 *
 * 缺失字段处理：
 *   - familiarity_short 缺失 → 视为 +Infinity（最不紧迫）
 *   - review_count 缺失 → 视为 0
 *   - 完全平局时按 voc_spelling 字典序，保证稳定排序
 */
export function sortByValue(items: TodayItem[]): TodayItem[] {
  return [...items].sort((a, b) => {
    const fa = typeof a.familiarity_short === 'number' ? a.familiarity_short : Number.POSITIVE_INFINITY
    const fb = typeof b.familiarity_short === 'number' ? b.familiarity_short : Number.POSITIVE_INFINITY
    if (fa !== fb) return fa - fb
    const ra = typeof a.review_count === 'number' ? a.review_count : 0
    const rb = typeof b.review_count === 'number' ? b.review_count : 0
    if (ra !== rb) return rb - ra
    return (a.voc_spelling || '').localeCompare(b.voc_spelling || '')
  })
}

function rowKeyOf(spelling: string | undefined): string {
  return (spelling || '').trim().toLowerCase()
}

/**
 * 判断单行是否"可执行"。
 *
 * V1 近似规则：
 *   - 没有任何状态事件到达 → 视为可执行（默认 pending）
 *   - phase === 'skipped' → 不可执行
 *   - status === 'done' → 不可执行
 *   - 其他（pending / running / error / 任意 phase）→ 可执行
 *
 * error 状态视为可执行：用户可能想直接重试（T6b 入口）。
 */
export function isExecutable(state: RowState | undefined): boolean {
  if (!state) return true
  if (state.phase === 'skipped') return false
  if (state.status === 'done') return false
  return true
}

/**
 * 按"仅可执行项"过滤。不修改入参。
 */
export function filterExecutable(
  items: TodayItem[],
  rowStatusMap: Record<string, RowState>,
): TodayItem[] {
  return items.filter(it => isExecutable(rowStatusMap[rowKeyOf(it.voc_spelling)]))
}

/**
 * 找到首个 status='running' 的行 key（小写 spelling）。
 * T3 自动跟随用；没有 running 行则返回 null。
 *
 * 多个并发 running 时取首个出现项；插入顺序由调用方决定（V1 取 Object.entries 顺序）。
 */
export function findRunningKey(rowStatusMap: Record<string, RowState>): string | null {
  for (const [k, v] of Object.entries(rowStatusMap)) {
    if (v && v.status === 'running') return k
  }
  return null
}
