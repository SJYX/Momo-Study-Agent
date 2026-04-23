/**
 * pages/Iteration.tsx — 智能迭代：触发迭代 + 查看薄弱词。
 */
import { useState } from 'react'
import { apiPost } from '../api/client'
import { useTaskStore } from '../stores/tasks'
import type { TaskSubmitResponse } from '../api/types'
import { RefreshCw, Loader2 } from 'lucide-react'

export default function Iteration() {
  const [processing, setProcessing] = useState(false)
  const [error, setError] = useState('')
  const setActiveTask = useTaskStore(s => s.setActiveTask)

  const handleIterate = async () => {
    setProcessing(true)
    setError('')
    try {
      const res = await apiPost<TaskSubmitResponse>('/api/study/iterate')
      if (res.data?.task_id) setActiveTask(res.data.task_id)
    } catch (e) { setError(String(e)) }
    finally { setProcessing(false) }
  }

  return (
    <div className="p-6">
      <h2 className="text-2xl font-bold mb-1">智能迭代</h2>
      <p className="text-gray-500 mb-6">自动筛选薄弱单词，重新生成助记法并同步到墨墨</p>

      {error && <div className="bg-red-50 text-red-700 p-3 rounded mb-4">{error}</div>}

      <div className="bg-white rounded-lg shadow p-6 max-w-lg">
        <h3 className="font-medium mb-2">迭代流程说明</h3>
        <ol className="list-decimal list-inside text-sm text-gray-600 space-y-1 mb-4">
          <li>系统自动筛选薄弱单词（多维评分）</li>
          <li>Level 0：AI 打分选优现有助记</li>
          <li>Level 1+：强力重炼生成新助记</li>
          <li>结果同步到墨墨释义和助记</li>
        </ol>
        <button
          onClick={handleIterate}
          disabled={processing}
          className="flex items-center gap-2 bg-purple-600 text-white px-4 py-2 rounded-lg hover:bg-purple-700 disabled:opacity-50 transition-colors"
        >
          {processing ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
          启动智能迭代
        </button>
      </div>
    </div>
  )
}