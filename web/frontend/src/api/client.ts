/**
 * api/client.ts — 统一的 API 请求封装。
 *
 * 所有请求走 /api/* 前缀，Vite dev server 会代理到 FastAPI 后端。
 * 响应统一解包为 { ok, data, error, user_id } 格式。
 *
 * P0-T4: 自动注入 X-Momo-Profile header。
 *
 * 同步门控: 收到 503 + `SYNCING` 错误码时(pyturso 首次 bootstrap 中), 自动触发
 * 全局 sync gate 显示加载遮罩,前端不再把每个请求都报成"失败"。
 */
import { useSyncGateStore } from '../stores/syncGate'

export interface ApiResponse<T = unknown> {
  ok: boolean
  data: T | null
  error: { code: string; message: string } | null
  user_id: string
}

/** 503 + SYNCING 错误的专用 Error 类型, 业务层可以 instanceof 判断后忽略 / 不报错。 */
export class DbSyncingError extends Error {
  readonly profile: string | null
  constructor(profile: string | null) {
    super(`profile '${profile ?? '?'}' 数据库正在首次同步, 请稍候`)
    this.name = 'DbSyncingError'
    this.profile = profile
  }
}

function getProfileHeader(): Record<string, string> {
  const profile = sessionStorage.getItem('momo_active_profile')
  return profile ? { 'X-Momo-Profile': profile } : {}
}

export async function apiClient<T = unknown>(
  url: string,
  options?: RequestInit,
): Promise<ApiResponse<T>> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 15_000)
  const resolvedUrl = new URL(url, window.location.origin).toString()

  let res: Response
  try {
    res = await fetch(resolvedUrl, {
      headers: {
        'Content-Type': 'application/json',
        ...getProfileHeader(),
        ...options?.headers,
      },
      signal: controller.signal,
      ...options,
    })
  } catch (e) {
    clearTimeout(timeout)
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new Error(`请求超时: ${resolvedUrl} (origin=${window.location.origin})`)
    }
    throw new Error(`无法连接后端: ${resolvedUrl} (origin=${window.location.origin})`)
  } finally {
    clearTimeout(timeout)
  }

  // 503 + SYNCING: 后端 DB 还在 bootstrap, 触发全局 sync gate 并抛 DbSyncingError
  if (res.status === 503) {
    let body: ApiResponse<unknown> | null = null
    try {
      body = (await res.clone().json()) as ApiResponse<unknown>
    } catch {
      // 不是 JSON 响应, 走通用 HTTP 错误分支
    }
    if (body?.error?.code === 'SYNCING') {
      const profile = sessionStorage.getItem('momo_active_profile')
      useSyncGateStore.getState().setSyncing(true, profile)
      throw new DbSyncingError(profile)
    }
  }

  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  }

  const json: ApiResponse<T> = await res.json()

  if (!json.ok && json.error) {
    throw new Error(`[${json.error.code}] ${json.error.message}`)
  }

  return json
}

export async function apiGet<T = unknown>(url: string): Promise<ApiResponse<T>> {
  return apiClient<T>(url)
}

export async function apiPost<T = unknown>(
  url: string,
  body?: unknown,
): Promise<ApiResponse<T>> {
  return apiClient<T>(url, {
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  })
}

export async function apiPut<T = unknown>(
  url: string,
  body?: unknown,
): Promise<ApiResponse<T>> {
  return apiClient<T>(url, {
    method: 'PUT',
    body: body ? JSON.stringify(body) : undefined,
  })
}

export async function apiDelete<T = unknown>(url: string): Promise<ApiResponse<T>> {
  return apiClient<T>(url, {
    method: 'DELETE',
  })
}
