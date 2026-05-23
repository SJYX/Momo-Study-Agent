import { Outlet } from 'react-router-dom'
import Sidebar from './components/layout/Sidebar'
import TaskDrawer from './components/tasks/TaskDrawer'
import SyncGate from './components/SyncGate'
import { useProfileChangeEffect } from './hooks/useProfileChangeEffect'

function App() {
  useProfileChangeEffect()

  return (
    <div className="flex min-h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
      <TaskDrawer />
      <SyncGate />
    </div>
  )
}

export default App