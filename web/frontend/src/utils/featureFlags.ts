/**
 * utils/featureFlags.ts — V1 Feature Flag 工具。
 *
 * 三层覆盖（从高到低优先级）：
 *   1. URL 参数：?ff_<key>=on | ?ff_<key>=off
 *   2. localStorage：ff_<key> = "on" | "off"
 *   3. 环境变量：VITE_FF_<KEY>=on（构建期默认值）
 *   4. 硬编码默认值（registry 里写死）
 *
 * 一键全关：
 *   URL：?ff_off=v1
 *   localStorage：ff_off = "v1"
 *
 *   killSwitch 只对 `killable: true` 的 V1 flag 生效。
 *   per-flag URL/localStorage override 仍可单独打开（即 kill 之后还能针对性开启）。
 *
 * Bulk Guard 例外：
 *   ff_today_bulk_guard 是安全护栏（>100 二次确认），killable: false。
 *   只能通过显式 URL/localStorage 设置 off 才能关闭。
 *
 * V1 默认全部 OFF：
 *   T1-T8 各自的 flag 默认 false，未开启时 Today 行为与 v2 修订前一致。
 *   T7 的 ff_today_bulk_guard 默认 true（安全护栏始终在）。
 *
 * 测试：
 *   evaluateFlag(key, defaultValue, sources) 是纯函数，便于 vitest 单测。
 *   isEnabled(key) 在浏览器环境直接读 window.location 与 localStorage。
 */

export const BULK_RETRY_THRESHOLD = 100

/**
 * V1 Flag 注册表。新增 flag 必须在此声明默认值与 killable 标记。
 *
 * killable=true：受 ff_off=v1 一键全关影响。
 * killable=false：必须显式 off 才能关闭（用于安全护栏）。
 */
export interface FlagDefinition {
  /** 默认值（未配置任何 override 时使用） */
  default: boolean
  /** 是否受 ff_off=v1 一键全关影响 */
  killable: boolean
  /** 关联任务编号，便于追溯 */
  task: string
}

export const V1_FLAGS = {
  ff_today_default_view: { default: false, killable: true, task: 'T1' },
  ff_today_light_confirm: { default: false, killable: true, task: 'T2' },
  ff_today_follow_running: { default: false, killable: true, task: 'T3' },
  ff_today_summary_stay: { default: false, killable: true, task: 'T4' },
  ff_today_failure_groups: { default: false, killable: true, task: 'T5' },
  ff_today_group_retry: { default: false, killable: true, task: 'T6b' },
  ff_today_bulk_guard: { default: true, killable: false, task: 'T7' },
  ff_today_residual_highlight: { default: false, killable: true, task: 'T8' },
} as const satisfies Record<string, FlagDefinition>

export type FlagKey = keyof typeof V1_FLAGS

/**
 * Flag 评估的输入源。所有字段可选，缺省视为不存在。
 * 设计为纯函数依赖以便 vitest 在 jsdom 之外也能测试。
 */
export interface FlagOverrideSources {
  urlParams?: URLSearchParams
  localStorage?: { getItem: (key: string) => string | null }
  env?: Record<string, string | undefined>
}

const TRUTHY = new Set(['on', 'true', '1', 'yes'])
const FALSY = new Set(['off', 'false', '0', 'no'])

function parseOverride(raw: string | null | undefined): boolean | null {
  if (raw == null) return null
  const v = String(raw).trim().toLowerCase()
  if (TRUTHY.has(v)) return true
  if (FALSY.has(v)) return false
  return null
}

function isKillSwitchActive(sources: FlagOverrideSources): boolean {
  const { urlParams, localStorage } = sources
  const fromUrl = urlParams?.get('ff_off')?.trim().toLowerCase()
  if (fromUrl === 'v1') return true
  const fromLs = localStorage?.getItem('ff_off')?.trim().toLowerCase()
  if (fromLs === 'v1') return true
  return false
}

/**
 * 评估一个 flag 的最终值。纯函数，无副作用。
 *
 * @param key Flag 名（必须在 V1_FLAGS 中注册）
 * @param sources 三层 override 输入源
 * @returns 最终生效的 boolean 值
 */
export function evaluateFlag(key: FlagKey, sources: FlagOverrideSources): boolean {
  const def = V1_FLAGS[key]
  if (!def) {
    // 未注册的 flag 默认 off，避免静默放行
    return false
  }

  // Layer 1: URL per-flag override（最高优先级）
  const urlOverride = parseOverride(sources.urlParams?.get(key))
  if (urlOverride !== null) return urlOverride

  // Layer 2: localStorage per-flag override
  const lsOverride = parseOverride(sources.localStorage?.getItem(key))
  if (lsOverride !== null) return lsOverride

  // Layer 3: kill switch（只对 killable flag 生效）
  if (def.killable && isKillSwitchActive(sources)) {
    return false
  }

  // Layer 4: 环境变量
  const envKey = `VITE_${key.toUpperCase()}`
  const envOverride = parseOverride(sources.env?.[envKey])
  if (envOverride !== null) return envOverride

  // Layer 5: 硬编码默认值
  return def.default
}

/**
 * 浏览器环境下的便捷封装。在非浏览器环境（如 vitest 单测）请直接用 evaluateFlag。
 */
export function isEnabled(key: FlagKey): boolean {
  const sources: FlagOverrideSources = {}
  if (typeof window !== 'undefined') {
    try {
      sources.urlParams = new URLSearchParams(window.location.search)
    } catch {
      /* ignore */
    }
    try {
      sources.localStorage = window.localStorage
    } catch {
      /* ignore: localStorage 在某些隐私模式下抛错 */
    }
  }
  // import.meta.env 由 Vite 注入，在测试环境也可用（值类型为 Record<string, string>）
  try {
    sources.env = import.meta.env as unknown as Record<string, string | undefined>
  } catch {
    /* ignore */
  }
  return evaluateFlag(key, sources)
}

/**
 * 调试工具：导出一份当前所有 V1 flag 的最终值快照。
 * 控制台调用：window.__momoFlags?.()
 */
export function snapshotFlags(): Record<FlagKey, boolean> {
  const out: Partial<Record<FlagKey, boolean>> = {}
  for (const k of Object.keys(V1_FLAGS) as FlagKey[]) {
    out[k] = isEnabled(k)
  }
  return out as Record<FlagKey, boolean>
}

// 暴露到 window 方便手动调试（不影响生产构建尺寸）
if (typeof window !== 'undefined') {
  ;(window as unknown as { __momoFlags?: () => Record<FlagKey, boolean> }).__momoFlags = snapshotFlags
}
