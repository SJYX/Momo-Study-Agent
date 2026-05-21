/**
 * pages/UserGateway.tsx — 用户入口网关：选择/新建 profile + 可选配置。
 *
 * Step 1: 选择已有 profile 或输入新名称
 * Step 2: 配置 token/AI provider（可跳过）
 *
 * P0-T1（React Query 改造版）：列表用 useQuery；创建/切换/保存/验证用 useMutation。
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useProfileStore } from '../stores/profile'
import { apiClient, apiPost, apiPut, apiPutWithRetry } from '../api/client'
import { queryKeys } from '../queries/queryClient'
import ErrorBanner from '../components/ui/ErrorBanner'
import type { UsersListResponse, UserProfile, ValidateResponse, ProfileCreateResponse } from '../api/types'
import { User, Plus, ArrowRight, ArrowLeft, Loader2, CheckCircle2, XCircle, SkipForward } from 'lucide-react'

type Step = 'select' | 'configure'

export default function UserGateway() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { activeProfile, setActiveProfile } = useProfileStore()

  const [step, setStep] = useState<Step>('select')
  const [newName, setNewName] = useState('')
  const [configName, setConfigName] = useState('')
  const [momoToken, setMomoToken] = useState('')
  const [provider, setProvider] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [validateResult, setValidateResult] = useState<Record<string, ValidateResponse>>({})
  const [actionError, setActionError] = useState('')
  const [isSwitching, setIsSwitching] = useState(false)

  // 列表查询（与 Users 页共享 cache key）
  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.users(),
    queryFn: async () => {
      const r = await apiClient<UsersListResponse>('/api/users')
      return r.data
    },
  })
  const profiles = data?.users ?? []

  // 验证字段
  const validateMutation = useMutation({
    mutationFn: async ({ field, value }: { field: string; value: string }) => {
      const res = await apiPost<ValidateResponse>('/api/users/validate', { field, value })
      return { field, result: res.data }
    },
    onSuccess: ({ field, result }) => {
      if (result) setValidateResult(prev => ({ ...prev, [field]: result }))
    },
    onError: (e, vars) => {
      setValidateResult(prev => ({
        ...prev,
        [vars.field]: { field: vars.field, valid: false, message: String(e) },
      }))
    },
  })

  // 创建新 profile（仅名称）
  const createMutation = useMutation({
    mutationFn: async () => {
      const name = newName.trim().toLowerCase()
      if (!name) throw new Error('用户名不能为空')
      await apiPost<ProfileCreateResponse>('/api/users', { profile_name: name })
      return name
    },
    onSuccess: (name) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.users() })
      setConfigName(name)
      setStep('configure')
      setActionError('')
    },
    onError: (e) => setActionError(String(e instanceof Error ? e.message : e)),
  })

  // 保存配置
  const saveConfigMutation = useMutation({
    mutationFn: async () => {
      if (momoToken || provider) {
        await apiPut(`/api/users/${encodeURIComponent(configName)}/config`, {
          momo_token: momoToken || undefined,
          ai_provider: provider || undefined,
          ai_api_key: apiKey || undefined,
        })
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.users() })
      finishAndEnter(configName)
    },
    onError: (e) => setActionError(String(e instanceof Error ? e.message : e)),
  })

  const finishAndEnter = async (name: string) => {
    setActiveProfile(name)
    setIsSwitching(true)
    try {
      await apiPutWithRetry(`/api/users/active?username=${encodeURIComponent(name)}`)
    } catch {
      // Non-blocking
    }
    navigate('/', { replace: true })
  }

  const handleSelectExisting = async (username: string) => {
    setActiveProfile(username)
    setIsSwitching(true)
    try {
      await apiPutWithRetry(`/api/users/active?username=${encodeURIComponent(username)}`)
    } catch {
      // Non-blocking: even if PUT fails, navigate — next request will re-init
    }
    navigate('/', { replace: true })
  }

  const errMsg = actionError
    || (error ? String(error instanceof Error ? error.message : error) : '')
  const validating = validateMutation.isPending
  const creating = createMutation.isPending
  const saving = saveConfigMutation.isPending
  const showCurrentProfileHint = activeProfile && step === 'select'

  if (isSwitching) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <Loader2 size={40} className="animate-spin text-blue-600 mx-auto mb-4" />
          <p className="text-gray-600 text-sm">正在初始化用户上下文...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="w-full max-w-lg">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-100 rounded-2xl mb-4">
            <User size={32} className="text-blue-600" />
          </div>
          <h1 className="text-2xl font-bold text-gray-900">MoMo Study Agent</h1>
          <p className="text-gray-500 mt-1">
            {step === 'select' ? '选择或创建一个 profile 开始学习' : '配置你的墨墨 Token 和 AI 引擎'}
          </p>
        </div>

        <ErrorBanner message={errMsg} />

        {/* Step 1: Select / Create */}
        {step === 'select' && (
          <div className="bg-white rounded-xl shadow-sm border p-6">
            {showCurrentProfileHint && (
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-4 flex items-center justify-between">
                <span className="text-sm text-blue-700">
                  当前: <strong>{activeProfile}</strong>
                </span>
                <button
                  onClick={() => navigate('/', { replace: true })}
                  className="text-sm text-blue-600 hover:text-blue-800 font-medium flex items-center gap-1"
                >
                  继续 <ArrowRight size={14} />
                </button>
              </div>
            )}

            <h3 className="text-sm font-medium text-gray-700 mb-3">已有 Profile</h3>
            {isLoading ? (
              <div className="flex items-center justify-center py-6 text-gray-400">
                <Loader2 size={20} className="animate-spin mr-2" /> 加载中...
              </div>
            ) : profiles.length > 0 ? (
              <div className="space-y-2 mb-6">
                {profiles.map((p: UserProfile) => (
                  <button
                    key={p.username}
                    onClick={() => handleSelectExisting(p.username)}
                    className={`w-full text-left px-4 py-3 rounded-lg border transition-all hover:border-blue-400 hover:bg-blue-50 ${
                      p.username === activeProfile ? 'border-blue-500 bg-blue-50' : 'border-gray-200'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className="bg-gray-100 p-2 rounded-full">
                          <User size={16} className="text-gray-600" />
                        </div>
                        <div>
                          <span className="font-medium text-gray-900">{p.username}</span>
                          <div className="flex items-center gap-3 mt-0.5 text-xs text-gray-500">
                            <span>{p.ai_provider || '未配置 AI'}</span>
                            {p.has_momo_token ? (
                              <span className="flex items-center gap-0.5 text-green-600">
                                <CheckCircle2 size={10} /> Token
                              </span>
                            ) : (
                              <span className="flex items-center gap-0.5 text-gray-400">
                                <XCircle size={10} /> Token
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                      <ArrowRight size={16} className="text-gray-400" />
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <div className="text-center py-6 text-gray-400 text-sm mb-6">暂无 profile，请创建一个</div>
            )}

            <h3 className="text-sm font-medium text-gray-700 mb-3">新建 Profile</h3>
            <div className="flex gap-2">
              <input
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value.toLowerCase())}
                onKeyDown={(e) => e.key === 'Enter' && createMutation.mutate()}
                placeholder="输入用户名（小写，不重复）"
                className="flex-1 border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              <button
                onClick={() => createMutation.mutate()}
                disabled={creating || !newName.trim()}
                className="flex items-center gap-1 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                创建
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Configure (skippable) */}
        {step === 'configure' && (
          <div className="bg-white rounded-xl shadow-sm border p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-gray-700">配置 {configName}</h3>
              <span className="text-xs text-gray-400">可跳过，稍后在设置中配置</span>
            </div>

            {/* MOMO Token */}
            <div className="mb-4">
              <div className="flex items-center justify-between mb-1">
                <label className="block text-sm font-medium text-gray-700">墨墨 Token</label>
                {momoToken && (
                  <button
                    onClick={() => validateMutation.mutate({ field: 'momo_token', value: momoToken })}
                    disabled={validating}
                    className="text-xs text-blue-600 hover:text-blue-800 disabled:opacity-40"
                  >
                    {validating ? '验证中...' : '验证'}
                  </button>
                )}
              </div>
              <input
                type="password"
                value={momoToken}
                onChange={(e) => setMomoToken(e.target.value)}
                placeholder="墨墨记忆助手 Token"
                className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              {validateResult['momo_token'] && (
                <div className={`text-xs mt-1 ${validateResult['momo_token'].valid ? 'text-green-600' : 'text-red-600'}`}>
                  {validateResult['momo_token'].valid ? '✓' : '✗'} {validateResult['momo_token'].message}
                </div>
              )}
            </div>

            {/* AI Provider */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">AI 引擎</label>
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              >
                <option value="">跳过</option>
                <option value="mimo">Mimo</option>
                <option value="gemini">Gemini</option>
              </select>
            </div>

            {/* AI API Key */}
            {provider && (
              <div className="mb-4">
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-sm font-medium text-gray-700">{provider.toUpperCase()} API Key</label>
                  {apiKey && (
                    <button
                      onClick={() => validateMutation.mutate({ field: `${provider}_api_key`, value: apiKey })}
                      disabled={validating}
                      className="text-xs text-blue-600 hover:text-blue-800 disabled:opacity-40"
                    >
                      {validating ? '验证中...' : '验证'}
                    </button>
                  )}
                </div>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={`${provider.toUpperCase()} API Key`}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
                {validateResult[`${provider}_api_key`] && (
                  <div className={`text-xs mt-1 ${validateResult[`${provider}_api_key`].valid ? 'text-green-600' : 'text-red-600'}`}>
                    {validateResult[`${provider}_api_key`].valid ? '✓' : '✗'} {validateResult[`${provider}_api_key`].message}
                  </div>
                )}
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setStep('select')}
                className="flex items-center gap-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg text-sm hover:bg-gray-50 transition-colors"
              >
                <ArrowLeft size={14} /> 返回
              </button>
              <button
                onClick={() => finishAndEnter(configName)}
                className="flex items-center gap-1 px-4 py-2 border border-gray-300 text-gray-500 rounded-lg text-sm hover:bg-gray-50 transition-colors"
              >
                <SkipForward size={14} /> 跳过
              </button>
              <button
                onClick={() => saveConfigMutation.mutate()}
                disabled={saving}
                className="flex-1 flex items-center justify-center gap-1 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {saving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                {saving ? '保存中...' : '完成'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
