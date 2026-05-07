import { describe, it, expect } from 'vitest'
import { buildFailureGroups } from './failureGrouping'
import type { TodayItem } from '../api/types'
import type { RowState } from './rowProgress'

describe('failureGrouping', () => {
  it('should ignore non-error items', () => {
    const items: TodayItem[] = [
      { voc_id: '1', voc_spelling: 'apple' },
      { voc_id: '2', voc_spelling: 'banana' },
    ]
    const rowStatusMap: Record<string, RowState> = {
      apple: { status: 'done' },
      banana: { status: 'running' },
    }
    const groups = buildFailureGroups(items, rowStatusMap)
    expect(groups).toHaveLength(0)
  })

  it('should group by error_type first, then error_code, then phase', () => {
    const items: TodayItem[] = [
      { voc_id: '1', voc_spelling: 'apple' },
      { voc_id: '2', voc_spelling: 'banana' },
      { voc_id: '3', voc_spelling: 'cherry' },
      { voc_id: '4', voc_spelling: 'date' },
    ]
    const rowStatusMap: Record<string, RowState> = {
      apple: { status: 'error', error_type: 'NETWORK', error_code: '404', phase: 'gen' }, // should be type:NETWORK
      banana: { status: 'error', error_type: 'NETWORK', error_code: '500', phase: 'gen' }, // should be type:NETWORK
      cherry: { status: 'error', error_code: '500', phase: 'gen' }, // should be code:500
      date: { status: 'error', phase: 'gen' }, // should be phase:gen
    }

    const groups = buildFailureGroups(items, rowStatusMap)
    
    // 3 groups total: type:NETWORK (2 items), code:500 (1 item), phase:gen (1 item)
    expect(groups).toHaveLength(3)

    // sorted by size descending, so type:NETWORK is first
    expect(groups[0].groupKey).toBe('type:NETWORK')
    expect(groups[0].items).toHaveLength(2)

    // other two have size 1, order depends on insertion (code:500 then phase:gen)
    const codeGroup = groups.find(g => g.groupKey === 'code:500')
    expect(codeGroup).toBeDefined()
    expect(codeGroup?.items).toHaveLength(1)

    const phaseGroup = groups.find(g => g.groupKey === 'phase:gen')
    expect(phaseGroup).toBeDefined()
    expect(phaseGroup?.items).toHaveLength(1)
  })

  it('should fallback to unknown if no fields are provided', () => {
    const items: TodayItem[] = [{ voc_id: '1', voc_spelling: 'apple' }]
    const rowStatusMap: Record<string, RowState> = {
      apple: { status: 'error', reason: 'my custom error' },
    }
    const groups = buildFailureGroups(items, rowStatusMap)
    expect(groups).toHaveLength(1)
    expect(groups[0].groupKey).toBe('phase:unknown')
    expect(groups[0].reason).toBe('my custom error')
  })
})
