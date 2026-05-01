import type { TaskEvent } from '../api/types'

export type RowStatus = 'pending' | 'running' | 'done' | 'error'

export interface RowState {
  status: RowStatus
  reason?: string
  phase?: string
  current?: number
  total?: number
}

/**
 * 把任务事件流投影成"按词→当前状态"的映射。
 *
 * P4-T2/T3 后只读 type='row_status' 的结构化事件 + 任务级 status；
 * 不再做日志关键字兜底解析。如果某个 item_id 从未出现在 row_status 事件里，
 * 它会保持 pending（直到任务终态时被强制收口）。
 */
export function buildRowStatusMap(
  items: Array<{ voc_spelling?: string }>,
  events: TaskEvent[],
  taskStatus: string,
): Record<string, RowState> {
  const map: Record<string, RowState> = {}
  for (const item of items) {
    const key = (item.voc_spelling || '').trim().toLowerCase()
    if (key) map[key] = { status: 'pending' }
  }

  for (const ev of events) {
    if (ev.type !== 'row_status') continue
    for (const row of ev.rows) {
      const key = String(row.item_id || '').trim().toLowerCase()
      if (!key || !map[key]) continue
      const st = row.status
      if (st !== 'pending' && st !== 'running' && st !== 'done' && st !== 'error') continue

      const next: RowState = { status: st }
      if (row.phase) next.phase = row.phase
      if (st === 'error' && row.error) next.reason = row.error
      if (typeof row.current === 'number') next.current = row.current
      if (typeof row.total === 'number') next.total = row.total
      map[key] = next
    }
  }

  if (taskStatus === 'done') {
    for (const key of Object.keys(map)) {
      if (map[key].status !== 'error') map[key] = { ...map[key], status: 'done' }
    }
  }
  if (taskStatus === 'error') {
    for (const key of Object.keys(map)) {
      if (map[key].status === 'pending' || map[key].status === 'running') {
        map[key] = { ...map[key], status: 'error', reason: map[key].reason || '任务异常终止' }
      }
    }
  }
  return map
}

export function rowStatusLabel(status: RowStatus): string {
  if (status === 'pending') return '待处理'
  if (status === 'running') return '处理中'
  if (status === 'done') return '已完成'
  return '失败'
}

export function rowPhaseLabel(phase?: string): string {
  if (!phase) return ''
  if (phase === 'skipped') return '已跳过'
  if (phase === 'ai_request') return 'AI 请求中'
  if (phase === 'ai_done') return 'AI 已完成'
  if (phase === 'sync_queued') return '已入同步队列'
  if (phase === 'sync_done') return '同步完成'
  if (phase === 'sync_pending') return '待同步'
  if (phase === 'sync_conflict') return '同步冲突'
  if (phase === 'sync_failed') return '同步失败'
  if (phase === 'ai_result') return '结果异常'
  return phase
}

export function rowDisplayLabel(state?: RowState): string {
  if (!state) return '待处理'
  if (state.phase === 'skipped') return '已跳过'
  if (state.phase === 'sync_pending') return '待同步'
  return rowStatusLabel(state.status)
}

/** V3：行级百分比（total 缺失或 0 时返回 null）。 */
export function rowPercent(state?: RowState): number | null {
  if (!state || typeof state.current !== 'number' || !state.total) return null
  const pct = (state.current / state.total) * 100
  return Math.max(0, Math.min(100, Math.round(pct)))
}
