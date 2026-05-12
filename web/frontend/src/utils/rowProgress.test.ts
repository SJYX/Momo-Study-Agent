import { describe, expect, it } from 'vitest'
import { buildRowStatusMap, rowDisplayLabel, rowStatusLabel } from './rowProgress'

describe('rowProgress utils', () => {
  it('正确映射后端传递的 6 种预设同步状态', () => {
    const items = [
      { voc_spelling: 'apple', status: 'sync_pending' },
      { voc_spelling: 'banana', status: 'done' },
      { voc_spelling: 'cat', status: 'sync_conflict' },
      { voc_spelling: 'dog', status: 'sync_queued' },
      { voc_spelling: 'elephant', status: 'syncing' },
      { voc_spelling: 'fox', status: 'sync_failed' },
      { voc_spelling: 'grape' }, // 无状态，默认 pending
    ]

    const map = buildRowStatusMap(items, [], 'idle')

    expect(map['apple']).toEqual({ status: 'done', phase: 'sync_pending' })
    expect(map['banana']).toEqual({ status: 'done' })
    expect(map['cat']).toEqual({ status: 'warning', phase: 'sync_conflict', reason: '远端释义冲突' })
    expect(map['dog']).toEqual({ status: 'done', phase: 'sync_queued' })
    expect(map['elephant']).toEqual({ status: 'done', phase: 'syncing' })
    expect(map['fox']).toEqual({ status: 'error', phase: 'sync_failed', reason: '同步终态失败' })
    expect(map['grape']).toEqual({ status: 'pending' })

    // 测试对应的精细 Label 显示逻辑
    expect(rowDisplayLabel(map['apple'])).toBe('待同步')
    expect(rowDisplayLabel(map['banana'])).toBe('已完成')
    expect(rowDisplayLabel(map['cat'])).toBe('同步冲突')
    expect(rowDisplayLabel(map['dog'])).toBe('同步排队中')
    expect(rowDisplayLabel(map['elephant'])).toBe('正在同步')
    expect(rowDisplayLabel(map['fox'])).toBe('同步失败')
    expect(rowDisplayLabel(map['grape'])).toBe('待处理')
  })
})
