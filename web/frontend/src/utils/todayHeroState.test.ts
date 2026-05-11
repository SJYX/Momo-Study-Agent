/**
 * todayHeroState.test.ts — Today Hero 四态判定纯函数测试。
 */
import { describe, expect, it } from 'vitest'
import { pickTodayHeroState } from './todayHeroState'

describe('pickTodayHeroState', () => {
  it('running 优先级最高', () => {
    expect(pickTodayHeroState({ isTaskRunning: true, isTerminal: false, itemsCount: 5 })).toBe('running')
    expect(pickTodayHeroState({ isTaskRunning: true, isTerminal: true, itemsCount: 0 })).toBe('running')
  })

  it('terminal 第二优先级', () => {
    expect(pickTodayHeroState({ isTaskRunning: false, isTerminal: true, itemsCount: 5 })).toBe('done')
    expect(pickTodayHeroState({ isTaskRunning: false, isTerminal: true, itemsCount: 0 })).toBe('done')
  })

  it('itemsCount 为 0 走 empty', () => {
    expect(pickTodayHeroState({ isTaskRunning: false, isTerminal: false, itemsCount: 0 })).toBe('empty')
  })

  it('默认走 idle', () => {
    expect(pickTodayHeroState({ isTaskRunning: false, isTerminal: false, itemsCount: 5 })).toBe('idle')
  })
})
