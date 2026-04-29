/**
 * stores/profile.ts — Profile store：管理 active profile，localStorage 持久化。
 *
 * P0-T2: 让用户刷新页面后不丢失当前 profile 选择。
 */
import { create } from 'zustand'

const STORAGE_KEY = 'momo_active_profile'

interface ProfileState {
  activeProfile: string | null
  setActiveProfile: (name: string) => void
  clearProfile: () => void
}

export const useProfileStore = create<ProfileState>((set) => ({
  activeProfile: localStorage.getItem(STORAGE_KEY),

  setActiveProfile: (name: string) => {
    localStorage.setItem(STORAGE_KEY, name)
    set({ activeProfile: name })
  },

  clearProfile: () => {
    localStorage.removeItem(STORAGE_KEY)
    set({ activeProfile: null })
  },
}))
