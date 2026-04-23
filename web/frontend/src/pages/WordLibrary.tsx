/**
 * pages/WordLibrary.tsx — 单词库：分页 + 搜索 + 筛选 + 详情 + 迭代历史。
 */
import { useEffect, useState, useCallback } from 'react'
import { apiClient } from '../api/client'
import type { WordsListResponse, WordNoteDetail, WordIterationsResponse, WordIteration } from '../api/types'
import { Search, ChevronLeft, ChevronRight, Eye, X, Save, Loader2, History } from 'lucide-react'

const SYNC_LABELS: Record<number, { label: string; cls: string }> = {
  0: { label: '待同步', cls: 'bg-yellow-100 text-yellow-700' },
  1: { label: '已同步', cls: 'bg-green-100 text-green-700' },
  2: { label: '冲突', cls: 'bg-red-100 text-red-700' },
}

export default function WordLibrary() {
  const [data, setData] = useState<WordsListResponse | null>(null)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [filterSync, setFilterSync] = useState<string>('')
  const [filterLevel, setFilterLevel] = useState<string>('')
  const [detail, setDetail] = useState<WordNoteDetail | null>(null)
  const [editMemory, setEditMemory] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [detailTab, setDetailTab] = useState<'note' | 'iterations'>('note')
  const [iterations, setIterations] = useState<WordIteration[]>([])
  const [loadingIterations, setLoadingIterations] = useState(false)

  const load = useCallback(() => {
    const params = new URLSearchParams({ page: String(page), page_size: '30' })
    if (search) params.set('search', search)
    if (filterSync) params.set('sync_status', filterSync)
    if (filterLevel) params.set('it_level', filterLevel)
    apiClient<WordsListResponse>(`/api/words?${params}`)
      .then(r => setData(r.data))
      .catch(e => setError(String(e)))
  }, [page, search, filterSync, filterLevel])

  useEffect(load, [load])

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setPage(1)
    setSearch(searchInput)
  }

  const handleFilterSync = (v: string) => {
    setFilterSync(v)
    setPage(1)
  }

  const handleFilterLevel = (v: string) => {
    setFilterLevel(v)
    setPage(1)
  }

  const openDetail = (vocId: string) => {
    setDetailTab('note')
    setIterations([])
    apiClient<WordNoteDetail>(`/api/words/${vocId}`)
      .then(r => {
        setDetail(r.data)
        setEditMemory(r.data?.memory_aid || '')
      })
      .catch(e => setError(String(e)))
  }

  const loadIterations = (vocId: string) => {
    setLoadingIterations(true)
    apiClient<WordIterationsResponse>(`/api/words/${vocId}/iterations`)
      .then(r => setIterations(r.data?.iterations || []))
      .catch(e => setError(String(e)))
      .finally(() => setLoadingIterations(false))
  }

  const switchTab = (tab: 'note' | 'iterations') => {
    setDetailTab(tab)
    if (tab === 'iterations' && detail && iterations.length === 0) {
      loadIterations(detail.voc_id)
    }
  }

  const handleSave = async () => {
    if (!detail) return
    setSaving(true)
    try {
      await apiClient(`/api/words/${detail.voc_id}`, {
        method: 'PUT',
        body: JSON.stringify({ memory_aid: editMemory }),
      })
      const res = await apiClient<WordNoteDetail>(`/api/words/${detail.voc_id}`)
      setDetail(res.data)
    } catch (e) { setError(String(e)) }
    finally { setSaving(false) }
  }

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0

  return (
    <div className="p-6">
      <h2 className="text-2xl font-bold mb-4">单词库</h2>

      {/* 搜索 + 筛选行 */}
      <div className="flex flex-wrap gap-2 mb-4 items-center">
        <form onSubmit={handleSearch} className="flex gap-2">
          <div className="relative flex-1 max-w-sm">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              placeholder="搜索单词..."
              className="w-full pl-9 pr-3 py-1.5 border rounded text-sm"
            />
          </div>
          <button type="submit" className="px-3 py-1.5 bg-gray-100 border rounded text-sm hover:bg-gray-200">搜索</button>
        </form>

        <select
          value={filterSync}
          onChange={e => handleFilterSync(e.target.value)}
          className="border rounded px-2 py-1.5 text-sm"
        >
          <option value="">所有同步状态</option>
          <option value="0">待同步</option>
          <option value="1">已同步</option>
          <option value="2">冲突</option>
        </select>

        <select
          value={filterLevel}
          onChange={e => handleFilterLevel(e.target.value)}
          className="border rounded px-2 py-1.5 text-sm"
        >
          <option value="">所有 Level</option>
          <option value="0">Level 0</option>
          <option value="1">Level 1</option>
          <option value="2">Level 2</option>
          <option value="3">Level 3</option>
          <option value="4">Level 4</option>
          <option value="5">Level 5</option>
        </select>

        {(filterSync || filterLevel) && (
          <button
            onClick={() => { handleFilterSync(''); handleFilterLevel(''); }}
            className="text-xs text-gray-500 hover:text-gray-700 underline"
          >
            清除筛选
          </button>
        )}
      </div>

      {error && <div className="bg-red-50 text-red-700 p-3 rounded mb-4 text-sm">{error}</div>}

      {data && (
        <>
          <div className="text-sm text-gray-500 mb-2">共 {data.total} 条记录</div>
          <div className="bg-white rounded-lg shadow overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50"><tr>
                <th className="text-left px-4 py-2 font-medium text-gray-600">单词</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">核心释义</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">Level</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">同步</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">创建时间</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">操作</th>
              </tr></thead>
              <tbody>{data.items.map(w => {
                const sync = SYNC_LABELS[w.sync_status] || SYNC_LABELS[0]
                return (
                  <tr key={w.voc_id} className="border-t hover:bg-gray-50">
                    <td className="px-4 py-2 font-medium">{w.spelling}</td>
                    <td className="px-4 py-2 text-gray-600 max-w-xs truncate">{w.basic_meanings || '—'}</td>
                    <td className="px-4 py-2">
                      <span className="inline-block px-2 py-0.5 rounded text-xs bg-blue-50 text-blue-700">L{w.it_level}</span>
                    </td>
                    <td className="px-4 py-2">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs ${sync.cls}`}>{sync.label}</span>
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-400">{w.created_at?.slice(0, 16)}</td>
                    <td className="px-4 py-2">
                      <button onClick={() => openDetail(w.voc_id)} className="text-blue-600 hover:text-blue-800" title="查看详情"><Eye size={14} /></button>
                    </td>
                  </tr>
                )
              })}</tbody>
            </table>
          </div>

          <div className="flex items-center justify-between mt-4">
            <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="flex items-center gap-1 px-3 py-1 border rounded text-sm disabled:opacity-40"><ChevronLeft size={14} /> 上一页</button>
            <span className="text-sm text-gray-500">第 {page} / {totalPages} 页</span>
            <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)} className="flex items-center gap-1 px-3 py-1 border rounded text-sm disabled:opacity-40">下一页 <ChevronRight size={14} /></button>
          </div>
        </>
      )}

      {/* Detail drawer */}
      {detail && (
        <div className="fixed inset-0 z-40 flex">
          <div className="absolute inset-0 bg-black/30" onClick={() => setDetail(null)} />
          <div className="ml-auto w-[520px] bg-white shadow-xl overflow-y-auto relative z-50">
            <div className="sticky top-0 bg-white border-b px-6 py-4 flex items-center justify-between z-10">
              <h3 className="text-xl font-bold">{detail.spelling}</h3>
              <button onClick={() => setDetail(null)} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
            </div>

            {/* Tabs */}
            <div className="flex border-b px-6">
              <button
                onClick={() => switchTab('note')}
                className={`px-4 py-2 text-sm font-medium border-b-2 ${detailTab === 'note' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
              >
                笔记详情
              </button>
              <button
                onClick={() => switchTab('iterations')}
                className={`px-4 py-2 text-sm font-medium border-b-2 flex items-center gap-1 ${detailTab === 'iterations' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
              >
                <History size={14} /> 迭代历史
              </button>
            </div>

            <div className="p-6">
              {detailTab === 'note' && (
                <>
                  {[
                    ['核心释义', detail.basic_meanings],
                    ['IELTS 考点', detail.ielts_focus],
                    ['固定搭配', detail.collocations],
                    ['陷阱', detail.traps],
                    ['近义词', detail.synonyms],
                    ['辨析', detail.discrimination],
                    ['例句', detail.example_sentences],
                  ].map(([label, value]) => value ? (
                    <div key={label} className="mb-3">
                      <div className="text-xs font-medium text-gray-500 mb-1">{label}</div>
                      <div className="text-sm whitespace-pre-wrap text-gray-700">{value}</div>
                    </div>
                  ) : null)}

                  {/* Memory Aid — 可编辑 */}
                  <div className="mb-3">
                    <div className="flex items-center justify-between mb-1">
                      <div className="text-xs font-medium text-gray-500">记忆法（可编辑）</div>
                      <button
                        onClick={handleSave}
                        disabled={saving || editMemory === detail.memory_aid}
                        className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 disabled:opacity-40"
                      >
                        {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                        保存
                      </button>
                    </div>
                    <textarea
                      value={editMemory}
                      onChange={e => setEditMemory(e.target.value)}
                      className="w-full border rounded p-2 text-sm font-mono min-h-[120px] resize-y"
                      rows={6}
                    />
                  </div>

                  {detail.word_ratings && (
                    <div className="mb-3">
                      <div className="text-xs font-medium text-gray-500 mb-1">评级</div>
                      <div className="text-sm whitespace-pre-wrap text-gray-700">{detail.word_ratings}</div>
                    </div>
                  )}
                </>
              )}

              {detailTab === 'iterations' && (
                <>
                  {loadingIterations && (
                    <div className="flex items-center justify-center py-8 text-gray-400">
                      <Loader2 size={20} className="animate-spin mr-2" /> 加载迭代历史...
                    </div>
                  )}
                  {!loadingIterations && iterations.length === 0 && (
                    <div className="text-center py-8 text-gray-400">暂无迭代记录</div>
                  )}
                  {iterations.map((it, idx) => (
                    <div key={idx} className="mb-4 border rounded-lg p-3">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-medium text-gray-500">{it.iteration_type}</span>
                        <span className="text-xs text-gray-400">{it.created_at?.slice(0, 16)}</span>
                      </div>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-sm font-bold text-blue-600">Score: {it.score}</span>
                        {it.tags && <span className="text-xs text-gray-500">{it.tags}</span>}
                      </div>
                      {it.justification && (
                        <div className="text-xs text-gray-600 mb-1">{it.justification}</div>
                      )}
                      {it.refined_content && (
                        <div className="text-sm whitespace-pre-wrap text-gray-700 bg-gray-50 rounded p-2 mt-1">{it.refined_content}</div>
                      )}
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
