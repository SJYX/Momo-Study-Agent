/**
 * pages/Users.tsx — 用户设置：profile 列表 + 创建向导 + 删除。
 */
import { useEffect, useState } from 'react'
import { apiClient, apiPost, apiPut } from '../api/client'
import type {
  UsersListResponse,
  UserProfile,
  WizardCreateResponse,
  ValidateResponse,
} from '../api/types'
import {
  User,
  CheckCircle2,
  XCircle,
  Plus,
  Trash2,
  Loader2,
  X,
  Shield,
} from 'lucide-react'

type WizardStep = 'idle' | 'form' | 'validating' | 'result'

export default function Users() {
  const [data, setData] = useState<UsersListResponse | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  // Wizard state
  const [wizardStep, setWizardStep] = useState<WizardStep>('idle')
  const [wizUsername, setWizUsername] = useState('')
  const [wizMomoToken, setWizMomoToken] = useState('')
  const [wizProvider, setWizProvider] = useState('')
  const [wizApiKey, setWizApiKey] = useState('')
  const [wizEmail, setWizEmail] = useState('')
  const [wizValidating, setWizValidating] = useState(false)
  const [wizValidateResult, setWizValidateResult] = useState<Record<string, ValidateResponse>>({})
  const [wizCreating, setWizCreating] = useState(false)
  const [wizResult, setWizResult] = useState<WizardCreateResponse | null>(null)
  const [wizError, setWizError] = useState('')

  // Delete state
  const [deleting, setDeleting] = useState<string | null>(null)
  const [switching, setSwitching] = useState<string | null>(null)
  const users = data?.users ?? []

  const load = () => {
    setLoading(true)
    apiClient<UsersListResponse>('/api/users')
      .then(r => setData(r.data))
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const handleValidateField = async (field: string, value: string) => {
    if (!value) return
    setWizValidating(true)
    try {
      const res = await apiPost<ValidateResponse>('/api/users/validate', { field, value })
      if (res.data) {
        setWizValidateResult(prev => ({ ...prev, [field]: res.data! }))
      }
    } catch (e) {
      setWizValidateResult(prev => ({
        ...prev,
        [field]: { field, valid: false, message: String(e) },
      }))
    } finally {
      setWizValidating(false)
    }
  }

  const handleCreate = async () => {
    if (!wizUsername.trim()) {
      setWizError('用户名不能为空')
      return
    }
    setWizCreating(true)
    setWizError('')
    try {
      const res = await apiPost<WizardCreateResponse>('/api/users/wizard', {
        username: wizUsername,
        momo_token: wizMomoToken,
        ai_provider: wizProvider,
        ai_api_key: wizApiKey,
        user_email: wizEmail,
      })
      if (res.data) {
        setWizResult(res.data)
        setWizardStep('result')
        load() // refresh list
      }
    } catch (e) {
      setWizError(String(e))
    } finally {
      setWizCreating(false)
    }
  }

  const handleSwitch = async (username: string) => {
    setSwitching(username)
    try {
      await apiPut(`/api/users/active?username=${encodeURIComponent(username)}`)
      // Notify all other pages to reload for the new user
      window.dispatchEvent(new CustomEvent('active-user-changed', { detail: { username } }))
      load() // refresh list to show new active user
    } catch (e) {
      setError(String(e))
    } finally {
      setSwitching(null)
    }
  }

  const handleDelete = async (username: string) => {
    if (!confirm(`确认删除用户 "${username}" 的本地 profile？此操作不可恢复。`)) return
    setDeleting(username)
    try {
      await apiClient(`/api/users/${username}`, { method: 'DELETE' })
      load()
    } catch (e) {
      setError(String(e))
    } finally {
      setDeleting(null)
    }
  }

  const closeWizard = () => {
    setWizardStep('idle')
    setWizUsername('')
    setWizMomoToken('')
    setWizProvider('')
    setWizApiKey('')
    setWizEmail('')
    setWizValidateResult({})
    setWizResult(null)
    setWizError('')
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold">用户设置</h2>
          <p className="text-gray-500">{data ? `当前用户: ${data.active_user}` : loading ? '加载中...' : ''}</p>
        </div>
        <button
          onClick={() => setWizardStep('form')}
          className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
        >
          <Plus size={14} /> 创建用户
        </button>
      </div>

      {error && <div className="bg-red-50 text-red-700 p-3 rounded mb-4 text-sm">{error}</div>}

      {data && (
        <div className="space-y-3 max-w-2xl">
          {users.map((u: UserProfile) => (
            <div
              key={u.username}
              className={`bg-white rounded-lg shadow p-4 flex items-center gap-4 transition-all ${
                u.is_active
                  ? 'ring-2 ring-blue-500 cursor-default'
                  : 'cursor-pointer hover:ring-2 hover:ring-blue-300 hover:shadow-md'
              } ${switching === u.username ? 'opacity-60' : ''}`}
              onClick={() => {
                if (!u.is_active && !switching) handleSwitch(u.username)
              }}
            >
              <div className="bg-gray-100 p-3 rounded-full">
                {switching === u.username ? (
                  <Loader2 size={20} className="text-blue-500 animate-spin" />
                ) : (
                  <User size={20} className="text-gray-600" />
                )}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{u.username}</span>
                  {u.is_active && <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded">当前</span>}
                  {!u.is_active && switching === u.username && (
                    <span className="text-xs text-blue-500">切换中...</span>
                  )}
                </div>
                <div className="flex items-center gap-4 mt-1 text-sm text-gray-500">
                  <span>AI: {u.ai_provider || '未配置'}</span>
                  <span className="flex items-center gap-1">
                    {u.has_momo_token ? <CheckCircle2 size={12} className="text-green-500" /> : <XCircle size={12} className="text-red-400" />}
                    墨墨 Token
                  </span>
                  <span className="flex items-center gap-1">
                    {u.has_ai_key ? <CheckCircle2 size={12} className="text-green-500" /> : <XCircle size={12} className="text-red-400" />}
                    AI Key
                  </span>
                </div>
              </div>
              {!u.is_active && (
                <button
                  onClick={e => { e.stopPropagation(); handleDelete(u.username) }}
                  disabled={deleting === u.username}
                  className="text-red-400 hover:text-red-600 disabled:opacity-40"
                  title="删除用户"
                >
                  {deleting === u.username ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
                </button>
              )}
            </div>
          ))}
          {users.length === 0 && (
            <div className="text-center py-8 text-gray-400">暂无用户，点击"创建用户"开始</div>
          )}
        </div>
      )}

      {/* Wizard Modal */}
      {wizardStep !== 'idle' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={closeWizard} />
          <div className="relative bg-white rounded-xl shadow-2xl w-[520px] max-h-[85vh] overflow-y-auto">
            <div className="sticky top-0 bg-white border-b px-6 py-4 flex items-center justify-between z-10">
              <h3 className="text-lg font-bold flex items-center gap-2">
                <Shield size={18} className="text-blue-600" />
                创建新用户
              </h3>
              <button onClick={closeWizard} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
            </div>

            <div className="p-6">
              {wizardStep === 'form' && (
                <>
                  {wizError && <div className="bg-red-50 text-red-700 p-3 rounded mb-4 text-sm">{wizError}</div>}

                  {/* Username */}
                  <div className="mb-4">
                    <label className="block text-sm font-medium text-gray-700 mb-1">用户名 *</label>
                    <input
                      type="text"
                      value={wizUsername}
                      onChange={e => setWizUsername(e.target.value.toLowerCase())}
                      placeholder="唯一标识，不区分大小写"
                      className="w-full border rounded px-3 py-2 text-sm"
                    />
                  </div>

                  {/* MOMO Token */}
                  <div className="mb-4">
                    <div className="flex items-center justify-between mb-1">
                      <label className="block text-sm font-medium text-gray-700">墨墨 Token</label>
                      {wizMomoToken && (
                        <button
                          onClick={() => handleValidateField('momo_token', wizMomoToken)}
                          disabled={wizValidating}
                          className="text-xs text-blue-600 hover:text-blue-800 disabled:opacity-40"
                        >
                          {wizValidating ? '验证中...' : '验证'}
                        </button>
                      )}
                    </div>
                    <input
                      type="password"
                      value={wizMomoToken}
                      onChange={e => setWizMomoToken(e.target.value)}
                      placeholder="墨墨记忆助手 Token"
                      className="w-full border rounded px-3 py-2 text-sm"
                    />
                    {wizValidateResult['momo_token'] && (
                      <div className={`text-xs mt-1 ${wizValidateResult['momo_token'].valid ? 'text-green-600' : 'text-red-600'}`}>
                        {wizValidateResult['momo_token'].valid ? '✅' : '❌'} {wizValidateResult['momo_token'].message}
                      </div>
                    )}
                  </div>

                  {/* AI Provider */}
                  <div className="mb-4">
                    <label className="block text-sm font-medium text-gray-700 mb-1">AI 引擎</label>
                    <select
                      value={wizProvider}
                      onChange={e => setWizProvider(e.target.value)}
                      className="w-full border rounded px-3 py-2 text-sm"
                    >
                      <option value="">跳过</option>
                      <option value="mimo">Mimo</option>
                      <option value="gemini">Gemini</option>
                    </select>
                  </div>

                  {/* AI API Key */}
                  {wizProvider && (
                    <div className="mb-4">
                      <div className="flex items-center justify-between mb-1">
                        <label className="block text-sm font-medium text-gray-700">{wizProvider.toUpperCase()} API Key</label>
                        {wizApiKey && (
                          <button
                            onClick={() => handleValidateField(`${wizProvider}_api_key`, wizApiKey)}
                            disabled={wizValidating}
                            className="text-xs text-blue-600 hover:text-blue-800 disabled:opacity-40"
                          >
                            {wizValidating ? '验证中...' : '验证'}
                          </button>
                        )}
                      </div>
                      <input
                        type="password"
                        value={wizApiKey}
                        onChange={e => setWizApiKey(e.target.value)}
                        placeholder={`${wizProvider.toUpperCase()} API Key`}
                        className="w-full border rounded px-3 py-2 text-sm"
                      />
                      {wizValidateResult[`${wizProvider}_api_key`] && (
                        <div className={`text-xs mt-1 ${wizValidateResult[`${wizProvider}_api_key`].valid ? 'text-green-600' : 'text-red-600'}`}>
                          {wizValidateResult[`${wizProvider}_api_key`].valid ? '✅' : '❌'} {wizValidateResult[`${wizProvider}_api_key`].message}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Email */}
                  <div className="mb-6">
                    <label className="block text-sm font-medium text-gray-700 mb-1">邮箱（可选）</label>
                    <input
                      type="email"
                      value={wizEmail}
                      onChange={e => setWizEmail(e.target.value)}
                      placeholder={`${wizUsername || 'user'}@momo-local`}
                      className="w-full border rounded px-3 py-2 text-sm"
                    />
                  </div>

                  <button
                    onClick={handleCreate}
                    disabled={wizCreating || !wizUsername.trim()}
                    className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
                  >
                    {wizCreating && <Loader2 size={16} className="animate-spin" />}
                    {wizCreating ? '创建中...' : '创建用户'}
                  </button>
                </>
              )}

              {wizardStep === 'result' && wizResult && (
                <div className="text-center py-4">
                  <div className="text-4xl mb-3">🎉</div>
                  <h4 className="text-lg font-bold mb-2">用户创建成功</h4>
                  <p className="text-gray-600 mb-4">{wizResult.message}</p>

                  <div className="bg-gray-50 rounded-lg p-4 text-left text-sm mb-4">
                    <div className="mb-2"><span className="font-medium">用户名:</span> {wizResult.username}</div>
                    <div className="mb-2"><span className="font-medium">云端数据库:</span> {wizResult.cloud_configured ? '✅ 已配置' : '❌ 未配置（本地模式）'}</div>

                    {(wizResult.validation && Object.keys(wizResult.validation).length > 0) && (
                      <div>
                        <span className="font-medium">验证结果:</span>
                        <ul className="mt-1 space-y-1">
                          {Object.entries(wizResult.validation ?? {}).map(([field, vr]) => (
                            <li key={field} className={vr.ok ? 'text-green-600' : 'text-red-600'}>
                              {vr.ok ? '✅' : '❌'} {field}: {typeof vr.detail === 'string' ? vr.detail : (vr.ok ? '通过' : '失败')}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>

                  <button
                    onClick={closeWizard}
                    className="px-6 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
                  >
                    完成
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
