/**
 * hooks/useTodayController.ts — TodayTasks 页面状态机与副作用集中管理。
 *
 * 把原 TodayTasks.tsx 内 13 处 useState、4 处 useEffect、若干 useMemo / useCallback
 * 抽到这里。组件层只负责把 hook 返回的状态/动作连到 JSX。
 *
 * 边界：
 * - DOM ref Map 仍由组件持有（hook 不直接访问 DOM），通过 registerRow / scrollToRow 协议交互。
 * - SSE 事件源（useTaskStore）保持不变，只是消费者从组件内挪到 hook 内。
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type RefObject,
} from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient, apiPost } from '../api/client'
import type { TodayItemsResponse, TaskSubmitResponse, HealthInfo } from '../api/types'
import { activeProfile } from '../queries/queryClient'
import { useTaskStore } from '../stores/tasks'
import { useOnActiveUserChanged } from './useOnActiveUserChanged'
import { buildRowStatusMap } from '../utils/rowProgress'
import { isEnabled, BULK_RETRY_THRESHOLD } from '../utils/featureFlags'
import { filterExecutable, findRunningKey, sortByValue } from '../utils/todayView'
import { buildFailureGroups } from '../utils/failureGrouping'

export type RowRefMap = RefObject<Map<string, HTMLTableRowElement>>

const todayQueryKey = (profile: string = activeProfile()) => ['today', profile] as const

export function useTodayController(rowRefs: RowRefMap) {
  const queryClient = useQueryClient()

  // -------------------------------------------------------------------------
  // 数据：今日列表（React Query）
  // -------------------------------------------------------------------------
  const { data, error, isFetching } = useQuery({
    queryKey: todayQueryKey(),
    queryFn: async () => {
      const r = await apiClient<TodayItemsResponse>('/api/study/today')
      return r.data
    },
  })

  useOnActiveUserChanged(() => {
    queryClient.invalidateQueries({ queryKey: ['today'] })
  })

  // -------------------------------------------------------------------------
  // DB 同步状态（加载等待期间每 3s 轮询）
  // -------------------------------------------------------------------------
  const { data: healthData } = useQuery({
    queryKey: ['health-poll', activeProfile()],
    queryFn: async () => {
      const r = await apiClient<HealthInfo>('/api/health')
      return r.data
    },
    refetchInterval: data ? false : 3000,  // 数据加载后停止轮询
    staleTime: 2000,
  })

  const dbSyncing = healthData?.db_sync?.syncing ?? false

  const items = data?.items ?? []

  // -------------------------------------------------------------------------
  // SSE / Task store 订阅
  // -------------------------------------------------------------------------
  const setActiveTask = useTaskStore(s => s.setActiveTask)
  const activeTaskId = useTaskStore(s => s.activeTaskId)
  const events = useTaskStore(s => s.events)
  const taskStatus = useTaskStore(s => s.taskStatus)

  // -------------------------------------------------------------------------
  // 局部状态机
  // -------------------------------------------------------------------------
  const [confirmingProcess, setConfirmingProcess] = useState(false)
  const [confirmingBulk, setConfirmingBulk] = useState(false)
  const [followPaused, setFollowPaused] = useState(false)
  const [showFailureMode, setShowFailureMode] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const [actionError, setActionError] = useState('')
  // 视图过滤与批量选择（新增）
  const [filterView, setFilterView] = useState<'all' | 'pending' | 'error' | 'new' | 'review'>('all')
  const [isBatchMode, setIsBatchMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  // -------------------------------------------------------------------------
  // Feature flags
  // -------------------------------------------------------------------------
  const flags = useMemo(() => ({
    defaultView: isEnabled('ff_today_default_view'),
    lightConfirm: isEnabled('ff_today_light_confirm'),
    followRunning: isEnabled('ff_today_follow_running'),
    summaryStay: isEnabled('ff_today_summary_stay'),
    failureGroups: isEnabled('ff_today_failure_groups'),
    bulkGuard: isEnabled('ff_today_bulk_guard'),
    groupRetry: isEnabled('ff_today_group_retry'),
  }), [])

  // -------------------------------------------------------------------------
  // 派生数据
  // -------------------------------------------------------------------------
  const rowStatusMap = useMemo(
    () => buildRowStatusMap(items, events, taskStatus),
    [items, events, taskStatus],
  )

  const sortedItems = useMemo(
    () => (flags.defaultView ? sortByValue(items) : items),
    [flags.defaultView, items],
  )

  const executableItems = useMemo(
    () => (flags.defaultView ? filterExecutable(sortedItems, rowStatusMap) : sortedItems),
    [flags.defaultView, sortedItems, rowStatusMap],
  )

  // 根据 filterView 派生显示列表
  const filteredItems = useMemo(() => {
    switch (filterView) {
      case 'pending':
        return sortedItems.filter(it => {
          const s = rowStatusMap[(it.voc_spelling || '').toLowerCase()]
          return !s || (s.phase !== 'skipped' && s.status !== 'done' && s.status !== 'error')
        })
      case 'error':
        return sortedItems.filter(it => rowStatusMap[(it.voc_spelling || '').toLowerCase()]?.status === 'error')
      case 'new':
        return sortedItems.filter(it => typeof it.review_count === 'number' && it.review_count === 0)
      case 'review':
        return sortedItems.filter(it => typeof it.review_count === 'number' && it.review_count > 0)
      case 'all':
      default:
        return flags.defaultView && !showAll ? executableItems : sortedItems
    }
  }, [filterView, sortedItems, rowStatusMap, flags.defaultView, showAll, executableItems])

  const displayItems = useMemo(() => {
    let list = [...filteredItems]

    // 动态置顶：执行中把 running 行移到顶部
    if (taskStatus === 'running' || taskStatus === 'pending') {
      list.sort((a, b) => {
        const aStatus = rowStatusMap[(a.voc_spelling || '').toLowerCase()]?.status
        const bStatus = rowStatusMap[(b.voc_spelling || '').toLowerCase()]?.status
        if (aStatus === 'running' && bStatus !== 'running') return -1
        if (aStatus !== 'running' && bStatus === 'running') return 1
        return 0
      })
    }
    return list
  }, [filteredItems, taskStatus, rowStatusMap])

  const hiddenCount = flags.defaultView ? sortedItems.length - executableItems.length : 0
  const runningKey = useMemo(() => findRunningKey(rowStatusMap), [rowStatusMap])
  const isTaskRunning = taskStatus === 'running' || taskStatus === 'pending'
  const isTerminal = taskStatus === 'done' || taskStatus === 'error' || taskStatus === 'canceled'

  const statusCounts = useMemo(() => {
    let done = 0, error = 0, skipped = 0
    for (const s of Object.values(rowStatusMap)) {
      if (!s) continue
      if (s.phase === 'skipped') skipped++
      else if (s.status === 'done') done++
      else if (s.status === 'error') error++
    }
    return { done, error, skipped }
  }, [rowStatusMap])

  const failureGroups = useMemo(() => {
    if (!flags.failureGroups || !showFailureMode) return []
    return buildFailureGroups(items, rowStatusMap)
  }, [items, rowStatusMap, flags.failureGroups, showFailureMode])

  // -------------------------------------------------------------------------
  // 副作用：自动滚动到 running 行
  // -------------------------------------------------------------------------
  const scrollToRow = useCallback((key: string) => {
    const el = rowRefs.current?.get(key)
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [rowRefs])

  useEffect(() => {
    if (!flags.followRunning || followPaused || !runningKey) return
    scrollToRow(runningKey)
  }, [flags.followRunning, followPaused, runningKey, scrollToRow])

  // 任务终态时重置暂停状态
  useEffect(() => {
    if (taskStatus === 'done' || taskStatus === 'error' || taskStatus === 'idle') {
      setFollowPaused(false)
    }
  }, [taskStatus])

  // -------------------------------------------------------------------------
  // 操作（mutations）
  // -------------------------------------------------------------------------
  const processMutation = useMutation({
    mutationFn: async (voc_ids?: string[]) => {
      const payload = voc_ids ? { voc_ids } : {}
      const res = await apiPost<TaskSubmitResponse>('/api/study/process', payload)
      return res.data
    },
    onSuccess: (data) => {
      if (data?.task_id) {
        setActiveTask(data.task_id)
      }
      setActionError('')
    },
    onError: (e) => setActionError(String(e instanceof Error ? e.message : e)),
    onSettled: () => setConfirmingProcess(false),
  })

  const cancelMutation = useMutation({
    mutationFn: async () => {
      if (!activeTaskId) return
      await apiPost(`/api/tasks/${activeTaskId}/cancel`)
    },
    onError: (e) => setActionError(String(e instanceof Error ? e.message : e)),
  })

  const refreshMutation = useMutation({
    mutationFn: async () => {
      const r = await apiClient<TodayItemsResponse>('/api/study/today?refresh=true')
      if (!r.data) throw new Error('刷新返回数据为空')
      return r.data
    },
    onSuccess: (newData) => {
      queryClient.setQueryData(todayQueryKey(), newData)
      setActionError('')
    },
    onError: (e) => setActionError(`刷新失败: ${e instanceof Error ? e.message : e}`),
  })

  const handleProcess = useCallback((voc_ids?: string[]) => {
    processMutation.mutate(voc_ids)
  }, [processMutation])

  const handleClick = useCallback(() => {
    if (flags.bulkGuard && executableItems.length > BULK_RETRY_THRESHOLD) {
      setConfirmingBulk(true)
    } else if (flags.lightConfirm) {
      setConfirmingProcess(true)
    } else {
      handleProcess()
    }
  }, [flags.bulkGuard, flags.lightConfirm, executableItems.length, handleProcess])

  const refresh = useCallback(() => {
    refreshMutation.mutate()
  }, [refreshMutation])

  const errorMsg = useMemo(() => {
    if (actionError) return actionError
    if (error) return String(error instanceof Error ? error.message : error)
    return ''
  }, [actionError, error])

  return {
    // 数据
    data,
    items,
    sortedItems,
    executableItems,
    displayItems,
    rowStatusMap,
    failureGroups,
    statusCounts,

    // 状态
    flags,
    confirmingProcess,
    confirmingBulk,
    followPaused,
    showFailureMode,
    showAll,
    activeTaskId,
    taskStatus,
    isTaskRunning,
    isTerminal,
    runningKey,
    hiddenCount,
    refreshing: isFetching || refreshMutation.isPending,
    processing: processMutation.isPending || cancelMutation.isPending,
    dbSyncing,
    errorMsg,

    // 新增视图与批量状态
    filterView,
    isBatchMode,
    selectedIds,
    filteredItemsCount: filteredItems.length,

    // 动作
    setConfirmingProcess,
    setConfirmingBulk,
    setFollowPaused,
    setShowFailureMode,
    setShowAll,
    setFilterView,
    setIsBatchMode,
    setSelectedIds,
    handleProcess,
    handleClick,
    handleCancel: cancelMutation.mutate,
    refresh,
  }
}

export type TodayController = ReturnType<typeof useTodayController>
