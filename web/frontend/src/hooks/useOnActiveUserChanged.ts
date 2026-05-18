/**
 * hooks/useOnActiveUserChanged.ts — 监听用户切换事件，触发回调。
 *
 * 用法：
 *   const load = useCallback(() => { ... }, [])
 *   useOnActiveUserChanged(load)
 */
import { useEffect } from 'react'

export function useOnActiveUserChanged(callback: () => void) {
  useEffect(() => {
    const handler = () => callback()
    window.addEventListener('active-user-changed', handler)
    return () => window.removeEventListener('active-user-changed', handler)
  }, [callback])
}