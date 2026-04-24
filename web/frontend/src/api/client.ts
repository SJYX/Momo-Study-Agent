/**
 * api/client.ts — 统一的 API 请求封装。
 *
 * 所有请求走 /api/* 前缀，Vite dev server 会代理到 FastAPI 后端。
 * 响应统一解包为 { ok, data, error, user_id } 格式。
 */

export interface ApiResponse<T = unknown> {
  ok: boolean
  data: T | null
  error: { code: string; message: string } | null
  user_id: string
}

export async function apiClient<T = unknown>(
  url: string,
  options?: RequestInit,
): Promise<ApiResponse<T>> {
  const res = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  })

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

export async function apiDelete<T = unknown>(url: string): Promise<ApiResponse<T>> {
  return apiClient<T>(url, {
    method: 'DELETE',
  })
}
