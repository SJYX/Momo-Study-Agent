import { Outlet } from 'react-router-dom'
import Sidebar from './components/layout/Sidebar'
import TaskDrawer from './components/tasks/TaskDrawer'

function App() {
  return (
    <div className="flex min-h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
      <TaskDrawer />
    </div>
  )
}

export default App