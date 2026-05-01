import type { TaskEvent } from '../api/types'

export type RowStatus = 'pending' | 'running' | 'done' | 'error'

function extractWordsFromMessage(message: string): string[] {
  if (!message.includes('[Pipeline]')) return []
  const marker = ' - '
  const idx = message.indexOf(marker)
  if (idx <= 0) return []
  const prefix = message.slice(0, idx).replace('[Pipeline]', '').trim()
  if (!prefix) return []
  return prefix.split(',').map((w) => w.trim().toLowerCase()).filter(Boolean)
}

export interface RowState {
  status: RowStatus
  reason?: string
  phase?: string
}

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
    if (ev.event === 'row_status') {
      const rows = (ev.data as { rows?: Array<{ item_id?: string; status?: string; error?: string }> } | undefined)?.rows || []
      for (const row of rows) {
        const key = String(row.item_id || '').trim().toLowerCase()
        if (!key || !map[key]) continue
        const st = String(row.status || '')
        if (st === 'pending' || st === 'running' || st === 'done' || st === 'error') {
          map[key] = st === 'error'
            ? { status: 'error', reason: row.error || '', phase: String((row as { phase?: string }).phase || '') }
            : { status: st, phase: String((row as { phase?: string }).phase || '') }
        }
      }
      continue
    }

    if (ev.type !== 'log') continue
    const msg = String(ev.message || '')
    const words = extractWordsFromMessage(msg)
    if (words.length === 0) continue

    let status: RowStatus | null = null
    if (msg.includes('开始请求 AI 助记')) status = 'running'
    if (msg.includes('已投递本地数据库及云端同步队列') || msg.includes('墨墨同步完成')) status = 'done'
    if (msg.includes('同步未完成') || msg.includes('异常') || msg.includes('失败')) status = 'error'
    if (!status) continue

    for (const word of words) {
      if (!map[word]) continue
      map[word] = status === 'error' ? { status, reason: msg } : { status }
    }
  }

  if (taskStatus === 'done') {
    for (const key of Object.keys(map)) {
      if (map[key].status !== 'error') map[key] = { status: 'done' }
    }
  }
  if (taskStatus === 'error') {
    for (const key of Object.keys(map)) {
      if (map[key].status === 'pending' || map[key].status === 'running') {
        map[key] = { status: 'error', reason: '任务异常终止' }
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
