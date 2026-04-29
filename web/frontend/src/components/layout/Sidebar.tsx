/**
 * components/layout/Sidebar.tsx — 左侧导航栏。
 */
import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  BookOpen,
  CalendarDays,
  RefreshCw,
  Library,
  RefreshCcw,
  Shield,
  Users,
  LogOut,
} from 'lucide-react'
import { useProfileStore } from '../../stores/profile'

const navItems = [
  { to: '/', label: '仪表盘', icon: LayoutDashboard },
  { to: '/today', label: '今日任务', icon: BookOpen },
  { to: '/future', label: '未来计划', icon: CalendarDays },
  { to: '/iteration', label: '智能迭代', icon: RefreshCw },
  { to: '/words', label: '单词库', icon: Library },
  { to: '/sync', label: '同步状态', icon: RefreshCcw },
  { to: '/preflight', label: '体检', icon: Shield },
  { to: '/users', label: '用户设置', icon: Users },
]

export default function Sidebar() {
  const activeProfile = useProfileStore((s) => s.activeProfile)
  const clearProfile = useProfileStore((s) => s.clearProfile)
  const navigate = useNavigate()

  const handleSwitchProfile = () => {
    clearProfile()
    navigate('/gateway', { replace: true })
  }

  return (
    <aside className="w-56 bg-gray-900 text-gray-100 flex flex-col min-h-screen">
      {/* Logo */}
      <div className="px-4 py-5 border-b border-gray-700">
        <h1 className="text-lg font-bold tracking-tight">MOMO Agent</h1>
        <p className="text-xs text-gray-400 mt-0.5">智能单词助记系统</p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 py-3 space-y-0.5">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                isActive
                  ? 'bg-gray-700 text-white font-medium'
                  : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
              }`
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Profile + Footer */}
      <div className="px-4 py-3 border-t border-gray-700">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-400 truncate">{activeProfile || '未选择'}</span>
          <button
            onClick={handleSwitchProfile}
            className="text-gray-500 hover:text-gray-300 transition-colors"
            title="切换 Profile"
          >
            <LogOut size={14} />
          </button>
        </div>
        <div className="text-xs text-gray-600">v1.0.0</div>
      </div>
    </aside>
  )
}