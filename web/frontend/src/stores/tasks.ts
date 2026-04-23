/**
 * stores/tasks.ts — Zustand store：全局任务状态管理。
 */
import { create } from 'zustand'
import type { TaskEvent } from '../api/types'

interface TaskState {
  // 当前活跃任务 ID
  activeTaskId: string | null
  // 任务状态
  taskStatus: string
  // 事件日志
  events: TaskEvent[]
  // TaskDrawer 是否展开
  drawerOpen: boolean
  // TaskDrawer 是否最小化
  drawerMinimized: boolean
  // actions
  setActiveTask: (taskId: string | null) => void
  setTaskStatus: (status: string) => void
  addEvent: (event: TaskEvent) => void
  clearEvents: () => void
  openDrawer: () => void
  closeDrawer: () => void
  toggleMinimize: () => void
  reset: () => void
}

export const useTaskStore = create<TaskState>((set) => ({
  activeTaskId: null,
  taskStatus: 'idle',
  events: [],
  drawerOpen: false,
  drawerMinimized: false,

  setActiveTask: (taskId) => set({ activeTaskId: taskId, taskStatus: taskId ? 'pending' : 'idle', events: [], drawerOpen: !!taskId, drawerMinimized: false }),
  setTaskStatus: (status) => set({ taskStatus: status }),
  addEvent: (event) => set((state) => ({ events: [...state.events, event] })),
  clearEvents: () => set({ events: [] }),
  openDrawer: () => set({ drawerOpen: true }),
  closeDrawer: () => set({ drawerOpen: false }),
  toggleMinimize: () => set((state) => ({ drawerMinimized: !state.drawerMinimized })),
  reset: () => set({ activeTaskId: null, taskStatus: 'idle', events: [], drawerOpen: false, drawerMinimized: false }),
}))