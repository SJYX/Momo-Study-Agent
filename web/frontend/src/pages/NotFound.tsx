/**
 * pages/NotFound.tsx — 404 页面。
 */
import { Link } from 'react-router-dom'
import { Home } from 'lucide-react'

export default function NotFound() {
  return (
    <div className="min-h-[60vh] flex items-center justify-center p-6">
      <div className="text-center">
        <div className="text-6xl font-bold text-gray-200 mb-4">404</div>
        <h2 className="text-xl font-bold text-gray-700 mb-2">页面未找到</h2>
        <p className="text-gray-500 mb-6">你访问的页面不存在或已被移除。</p>
        <Link
          to="/"
          className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700"
        >
          <Home size={14} /> 返回首页
        </Link>
      </div>
    </div>
  )
}