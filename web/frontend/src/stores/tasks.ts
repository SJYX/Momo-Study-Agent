/**
 * stores/tasks.ts — Zustand store：全局任务状态管理。
 *
 * V2 新增 iconMode：TaskDrawer Smart Icon 模式下，任务触发后先显示小图标而非全展开。
 */
import { create } from 'zustand'
import type { TaskEvent } from '../api/types'
import { isEnabled } from '../utils/featureFlags'

interface TaskState {
  // 当前活跃任务 ID
  activeTaskId: string | null
  // 任务状态
  taskStatus: string
  // 事件日志
  events: TaskEvent[]
  // TaskDrawer 是否展开（全尺寸面板）
  drawerOpen: boolean
  // TaskDrawer 是否最小化（小型横条）
  drawerMinimized: boolean
  // V2: Smart Icon 模式（右下角小图标）
  iconMode: boolean
  // actions
  setActiveTask: (taskId: string | null) => void
  setTaskStatus: (status: string) => void
  addEvent: (event: TaskEvent) => void
  clearEvents: () => void
  openDrawer: () => void
  closeDrawer: () => void
  toggleMinimize: () => void
  expandFromIcon: () => void
  collapseToIcon: () => void
  reset: () => void
}

export const useTaskStore = create<TaskState>((set) => ({
  activeTaskId: null,
  taskStatus: 'idle',
  events: [],
  drawerOpen: false,
  drawerMinimized: false,
  iconMode: false,

  setActiveTask: (taskId) => {
    const useIconMode = !!taskId && isEnabled('ff_taskdrawer_smart_icon')
    set({
      activeTaskId: taskId,
      taskStatus: taskId ? 'pending' : 'idle',
      events: [],
      drawerOpen: taskId ? !useIconMode : false,
      drawerMinimized: false,
      iconMode: useIconMode,
    })
  },
  setTaskStatus: (status) => set({ taskStatus: status }),
  addEvent: (event) => set((state) => ({ events: [...state.events, event] })),
  clearEvents: () => set({ events: [] }),
  openDrawer: () => set({ drawerOpen: true, drawerMinimized: false }),
  closeDrawer: () => set({ drawerOpen: false }),
  toggleMinimize: () => set((state) => ({ drawerMinimized: !state.drawerMinimized })),
  expandFromIcon: () => set({ drawerOpen: true, iconMode: false, drawerMinimized: false }),
  collapseToIcon: () => set({ drawerOpen: false, iconMode: true, drawerMinimized: false }),
  reset: () => set({ activeTaskId: null, taskStatus: 'idle', events: [], drawerOpen: false, drawerMinimized: false, iconMode: false }),
}))
