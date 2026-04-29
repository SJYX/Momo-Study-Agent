/**
 * api/client.ts — 统一的 API 请求封装。
 *
 * 所有请求走 /api/* 前缀，Vite dev server 会代理到 FastAPI 后端。
 * 响应统一解包为 { ok, data, error, user_id } 格式。
 *
 * P0-T4: 自动注入 X-Momo-Profile header。
 */

export interface ApiResponse<T = unknown> {
  ok: boolean
  data: T | null
  error: { code: string; message: string } | null
  user_id: string
}

function getProfileHeader(): Record<string, string> {
  const profile = localStorage.getItem('momo_active_profile')
  return profile ? { 'X-Momo-Profile': profile } : {}
}

export async function apiClient<T = unknown>(
  url: string,
  options?: RequestInit,
): Promise<ApiResponse<T>> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 15_000)

  let res: Response
  try {
    res = await fetch(url, {
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
      throw new Error('请求超时，请检查后端是否启动')
    }
    throw new Error('无法连接后端，请检查服务是否运行')
  } finally {
    clearTimeout(timeout)
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
