/**
 * components/today/TodayHero.tsx — Today 顶部 Hero 4 态分发。Spec §4.2。
 */
import { pickTodayHeroState } from '../../utils/todayHeroState'
import TodayHeroIdle from './TodayHeroIdle'
import TodayHeroRunning from './TodayHeroRunning'
import TodayHeroDone from './TodayHeroDone'
import TodayHeroEmpty from './TodayHeroEmpty'

export interface TodayHeroProps {
  isTaskRunning: boolean
  isTerminal: boolean
  totalCount: number
  executableCount: number
  doneCount: number
  errorCount: number
  skippedCount: number
  runningCount: number
  pendingCount: number
  currentWord: string | null
  currentPhase: string | null
  showAll: boolean
  onStart: () => void
  onCancel: () => void
  onToggleShowAll: () => void
  onViewFailures?: () => void
  onRetryBatch: () => void
  disabled?: boolean
  // 新增
  filteredCount?: number
  filterView?: string
  onRetryFailures?: () => void
}

export default function TodayHero(props: TodayHeroProps) {
  const state = pickTodayHeroState({
    isTaskRunning: props.isTaskRunning,
    isTerminal: props.isTerminal,
    itemsCount: props.totalCount,
  })

  if (state === 'running') {
    return (
      <TodayHeroRunning
        currentWord={props.currentWord}
        phase={props.currentPhase}
        doneCount={props.doneCount}
        runningCount={props.runningCount}
        errorCount={props.errorCount}
        pendingCount={props.pendingCount}
        totalCount={props.totalCount}
        onCancel={props.onCancel}
        disabled={props.disabled}
      />
    )
  }
  if (state === 'done') {
    return (
      <TodayHeroDone
        doneCount={props.doneCount}
        errorCount={props.errorCount}
        skippedCount={props.skippedCount}
        totalCount={props.totalCount}
        onViewFailures={props.onViewFailures}
        onRetryBatch={props.onRetryBatch}
      />
    )
  }
  if (state === 'empty') return <TodayHeroEmpty />
  return (
    <TodayHeroIdle
      totalCount={props.totalCount}
      doneCount={props.doneCount}
      errorCount={props.errorCount}
      filteredCount={props.filteredCount ?? props.totalCount}
      filterView={props.filterView ?? 'all'}
      onStart={props.onStart}
      disabled={props.disabled}
      onRetryFailures={props.onRetryFailures}
    />
  )
}
