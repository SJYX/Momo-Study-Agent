/**
 * components/ErrorBoundary.tsx — 全局错误边界，捕获未处理的渲染错误。
 */
import { Component, type ReactNode } from 'react'
import { AlertTriangle, RefreshCcw } from 'lucide-react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('[ErrorBoundary] 未捕获错误:', error, errorInfo)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
  }

  handleReload = () => {
    window.location.reload()
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50 p-6">
          <div className="max-w-md w-full bg-white rounded-xl shadow-lg p-8 text-center">
            <div className="inline-flex items-center justify-center w-16 h-16 bg-red-100 rounded-full mb-4">
              <AlertTriangle size={32} className="text-red-500" />
            </div>
            <h2 className="text-xl font-bold text-gray-800 mb-2">页面出现错误</h2>
            <p className="text-gray-500 text-sm mb-4">
              {this.state.error?.message || '发生了未知错误'}
            </p>
            <div className="bg-red-50 rounded-lg p-3 mb-6 text-left">
              <pre className="text-xs text-red-600 whitespace-pre-wrap break-all max-h-32 overflow-auto">
                {this.state.error?.stack?.split('\n').slice(0, 5).join('\n')}
              </pre>
            </div>
            <div className="flex gap-3 justify-center">
              <button
                onClick={this.handleReset}
                className="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50"
              >
                重试
              </button>
              <button
                onClick={this.handleReload}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700"
              >
                <RefreshCcw size={14} /> 重新加载
              </button>
            </div>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}