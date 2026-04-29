/**
 * components/RequireProfile.tsx — 路由守卫：未选 profile 时重定向到 UserGateway。
 *
 * P0-T3
 */
import { Navigate, Outlet } from 'react-router-dom'
import { useProfileStore } from '../stores/profile'

export default function RequireProfile() {
  const activeProfile = useProfileStore((s) => s.activeProfile)

  if (!activeProfile) {
    return <Navigate to="/gateway" replace />
  }

  return <Outlet />
}
