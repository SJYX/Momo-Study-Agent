/**
 * components/layout/SidebarV2.tsx — 暖色 Notion 风 Sidebar 重写。
 * 受 ff_redesign_sidebar 控制，由 Sidebar.tsx 分发。
 */
import { NavLink, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  Activity, LayoutDashboard, BookOpen, CalendarDays, RefreshCw,
  Library, RefreshCcw, Shield, Users, LogOut,
} from 'lucide-react'
import { useProfileStore } from '../../stores/profile'
import { isEnabled } from '../../utils/featureFlags'
import { prefetchForRoute } from '../../queries/prefetch'

const navItems = isEnabled('ff_ops_monitor')
  ? [
      { to: '/', label: '运维监控', icon: Activity },
      { to: '/today', label: '今日任务', icon: BookOpen },
      { to: '/future', label: '未来计划', icon: CalendarDays },
      { to: '/iteration', label: '智能迭代', icon: RefreshCw },
      { to: '/words', label: '单词库', icon: Library },
      { to: '/sync', label: '同步状态', icon: RefreshCcw },
      { to: '/preflight', label: '体检', icon: Shield },
      { to: '/dashboard', label: '仪表盘', icon: LayoutDashboard },
      { to: '/users', label: '用户设置', icon: Users },
    ]
  : [
      { to: '/', label: '仪表盘', icon: LayoutDashboard },
      { to: '/today', label: '今日任务', icon: BookOpen },
      { to: '/future', label: '未来计划', icon: CalendarDays },
      { to: '/iteration', label: '智能迭代', icon: RefreshCw },
      { to: '/words', label: '单词库', icon: Library },
      { to: '/sync', label: '同步状态', icon: RefreshCcw },
      { to: '/preflight', label: '体检', icon: Shield },
      { to: '/users', label: '用户设置', icon: Users },
    ]

export default function SidebarV2() {
  const activeProfile = useProfileStore((s) => s.activeProfile)
  const clearProfile = useProfileStore((s) => s.clearProfile)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const handleSwitchProfile = () => {
    clearProfile()
    navigate('/gateway', { replace: true })
  }

  return (
    <aside className="w-56 bg-surface-sidebar text-text-secondary flex flex-col min-h-screen border-r border-border-default">
      {/* Logo */}
      <div className="px-4 py-5 border-b border-border-default">
        <h1 className="text-lg font-bold tracking-tight text-text-primary">MOMO Agent</h1>
        <p className="text-xs text-text-muted mt-0.5">智能单词助记系统</p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 py-3 space-y-0.5">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            onMouseEnter={() => prefetchForRoute(queryClient, to)}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-button text-sm transition-colors ${
                isActive
                  ? 'bg-accent-soft text-accent-hover font-semibold'
                  : 'text-text-secondary hover:bg-surface-hover hover:text-text-primary'
              }`
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Profile + Footer */}
      <div className="px-4 py-3 border-t border-border-default">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-text-muted truncate">{activeProfile || '未选择'}</span>
          <button
            onClick={handleSwitchProfile}
            className="text-text-muted hover:text-text-primary transition-colors"
            title="切换 Profile"
          >
            <LogOut size={14} />
          </button>
        </div>
        <div className="text-xs text-text-muted opacity-60">v1.0.0</div>
      </div>
    </aside>
  )
}
