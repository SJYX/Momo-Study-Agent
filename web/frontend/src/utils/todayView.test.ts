/**
 * todayView.test.ts — Today 列表纯函数单测。
 */
import { describe, expect, it } from 'vitest'
import type { TodayItem } from '../api/types'
import type { RowState } from './rowProgress'
import { filterExecutable, findRunningKey, isExecutable, sortByValue } from './todayView'

function mk(
  spelling: string,
  familiarity_short?: number,
  review_count?: number,
): TodayItem {
  const item: TodayItem = { voc_id: spelling, voc_spelling: spelling }
  if (typeof familiarity_short === 'number') item.familiarity_short = familiarity_short
  if (typeof review_count === 'number') item.review_count = review_count
  return item
}

describe('sortByValue', () => {
  it('familiarity_short 升序作为主排序', () => {
    const out = sortByValue([mk('b', 0.8), mk('a', 0.2), mk('c', 0.5)])
    expect(out.map(i => i.voc_spelling)).toEqual(['a', 'c', 'b'])
  })

  it('相同 familiarity 时 review_count 降序作为次级排序', () => {
    const out = sortByValue([
      mk('a', 0.5, 1),
      mk('b', 0.5, 5),
      mk('c', 0.5, 3),
    ])
    expect(out.map(i => i.voc_spelling)).toEqual(['b', 'c', 'a'])
  })

  it('完全平局时按 spelling 字典序，保证稳定', () => {
    const out = sortByValue([mk('zz', 0.5, 1), mk('aa', 0.5, 1), mk('mm', 0.5, 1)])
    expect(out.map(i => i.voc_spelling)).toEqual(['aa', 'mm', 'zz'])
  })

  it('familiarity_short 缺失视为 +Infinity（排到最后）', () => {
    const out = sortByValue([mk('b'), mk('a', 0.5), mk('c', 0.1)])
    expect(out.map(i => i.voc_spelling)).toEqual(['c', 'a', 'b'])
  })

  it('review_count 缺失视为 0', () => {
    const out = sortByValue([
      mk('a', 0.5, 0),
      mk('b', 0.5),
      mk('c', 0.5, 5),
    ])
    // c (review 5) 优先，a/b 均视为 0，按 spelling 字典序
    expect(out.map(i => i.voc_spelling)).toEqual(['c', 'a', 'b'])
  })

  it('不修改入参', () => {
    const input = [mk('b', 0.8), mk('a', 0.2)]
    const before = input.map(i => i.voc_spelling)
    sortByValue(input)
    expect(input.map(i => i.voc_spelling)).toEqual(before)
  })
})

describe('isExecutable', () => {
  it('无状态事件视为可执行（默认 pending）', () => {
    expect(isExecutable(undefined)).toBe(true)
  })

  it('pending 视为可执行', () => {
    expect(isExecutable({ status: 'pending' } as RowState)).toBe(true)
  })

  it('running 视为可执行', () => {
    expect(isExecutable({ status: 'running' } as RowState)).toBe(true)
  })

  it('done 视为不可执行', () => {
    expect(isExecutable({ status: 'done' } as RowState)).toBe(false)
  })

  it('phase=skipped 视为不可执行（无论 status）', () => {
    expect(isExecutable({ status: 'pending', phase: 'skipped' } as RowState)).toBe(false)
    expect(isExecutable({ status: 'done', phase: 'skipped' } as RowState)).toBe(false)
  })

  it('error 视为可执行（允许重试）', () => {
    expect(isExecutable({ status: 'error', reason: 'AI 调用失败' } as RowState)).toBe(true)
  })
})

describe('filterExecutable', () => {
  it('过滤掉 done 与 skipped', () => {
    const items = [mk('alpha'), mk('Beta'), mk('GAMMA')]
    const map: Record<string, RowState> = {
      alpha: { status: 'done' },
      beta: { status: 'pending', phase: 'skipped' },
      gamma: { status: 'pending' },
    }
    const out = filterExecutable(items, map)
    expect(out.map(i => i.voc_spelling)).toEqual(['GAMMA'])
  })

  it('rowStatusMap 没有对应 key 时保留', () => {
    const items = [mk('alpha'), mk('beta')]
    const out = filterExecutable(items, {})
    expect(out.map(i => i.voc_spelling)).toEqual(['alpha', 'beta'])
  })

  it('error 状态保留（用户可能要重试）', () => {
    const items = [mk('alpha')]
    const map: Record<string, RowState> = {
      alpha: { status: 'error', reason: 'AI 调用失败' },
    }
    expect(filterExecutable(items, map)).toEqual(items)
  })

  it('大小写一致：spelling 任何大小写都按 lowercase 匹配', () => {
    const items = [mk('Hello'), mk('WORLD')]
    const map: Record<string, RowState> = {
      hello: { status: 'done' },
      world: { status: 'pending' },
    }
    const out = filterExecutable(items, map)
    expect(out.map(i => i.voc_spelling)).toEqual(['WORLD'])
  })
})

describe('findRunningKey', () => {
  it('返回首个 running key', () => {
    const map: Record<string, RowState> = {
      alpha: { status: 'pending' },
      beta: { status: 'running' },
      gamma: { status: 'running' },
    }
    expect(findRunningKey(map)).toBe('beta')
  })

  it('没有 running 时返回 null', () => {
    const map: Record<string, RowState> = {
      alpha: { status: 'pending' },
      beta: { status: 'done' },
    }
    expect(findRunningKey(map)).toBeNull()
  })

  it('空 map 返回 null', () => {
    expect(findRunningKey({})).toBeNull()
  })
})
