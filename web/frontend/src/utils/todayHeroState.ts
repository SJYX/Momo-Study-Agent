/**
 * utils/todayHeroState.ts — Today Hero 状态判定纯函数。
 *
 * 判定优先级（Spec §4.2）：
 *   isTaskRunning → isTerminal → itemsCount === 0 → 默认 idle
 */
export type TodayHeroState = 'idle' | 'running' | 'done' | 'empty'

export interface TodayHeroStateInput {
  isTaskRunning: boolean
  isTerminal: boolean
  itemsCount: number
}

export function pickTodayHeroState(input: TodayHeroStateInput): TodayHeroState {
  if (input.isTaskRunning) return 'running'
  if (input.isTerminal) return 'done'
  if (input.itemsCount === 0) return 'empty'
  return 'idle'
}
