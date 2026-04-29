/**
 * router.tsx — React Router 配置。
 *
 * P0-T3: 添加路由守卫，未选 profile 时重定向到 /gateway。
 */
import { createBrowserRouter } from 'react-router-dom'
import App from './App'
import RequireProfile from './components/RequireProfile'
import UserGateway from './pages/UserGateway'
import Dashboard from './pages/Dashboard'
import TodayTasks from './pages/TodayTasks'
import FuturePlan from './pages/FuturePlan'
import Iteration from './pages/Iteration'
import WordLibrary from './pages/WordLibrary'
import SyncStatus from './pages/SyncStatus'
import Preflight from './pages/Preflight'
import Users from './pages/Users'
import NotFound from './pages/NotFound'

export const router = createBrowserRouter([
  {
    path: '/gateway',
    element: <UserGateway />,
  },
  {
    element: <RequireProfile />,
    children: [
      {
        path: '/',
        element: <App />,
        children: [
          { index: true, element: <Dashboard /> },
          { path: 'today', element: <TodayTasks /> },
          { path: 'future', element: <FuturePlan /> },
          { path: 'iteration', element: <Iteration /> },
          { path: 'words', element: <WordLibrary /> },
          { path: 'sync', element: <SyncStatus /> },
          { path: 'preflight', element: <Preflight /> },
          { path: 'users', element: <Users /> },
          { path: '*', element: <NotFound /> },
        ],
      },
    ],
  },
])
