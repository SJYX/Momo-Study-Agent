/**
 * utils/featureFlags.ts — V1/V2 Feature Flag 工具。
 *
 * 三层覆盖（从高到低优先级）：
 *   1. URL 参数：?ff_<key>=on | ?ff_<key>=off
 *   2. localStorage：ff_<key> = "on" | "off"
 *   3. 环境变量：VITE_FF_<KEY>=on（构建期默认值）
 *   4. 硬编码默认值（registry 里写死）
 *
 * 一键全关：
 *   URL：?ff_off=v1（仅 V1）或 ?ff_off=v2（V1+V2 全关）
 *   localStorage：ff_off = "v1" 或 "v2"
 *
 * V1 flags（C02+C03）：ff_today_* 系列
 * V2 flags（C04+C05）：ff_taskdrawer_* / ff_ops_monitor_* 系列
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
  ff_today_default_view: { default: true, killable: true, task: 'T1' },
  ff_today_light_confirm: { default: true, killable: true, task: 'T2' },
  ff_today_follow_running: { default: true, killable: true, task: 'T3' },
  ff_today_summary_stay: { default: true, killable: true, task: 'T4' },
  ff_today_failure_groups: { default: true, killable: true, task: 'T5' },
  ff_today_group_retry: { default: true, killable: true, task: 'T6b' },
  ff_today_bulk_guard: { default: true, killable: false, task: 'T7' },
  ff_today_residual_highlight: { default: true, killable: true, task: 'T8' },
} as const satisfies Record<string, FlagDefinition>

/**
 * V2 Flag 注册表。C04 TaskDrawer Smart Icon + C05 Ops Monitor。
 *
 * killable=true：受 ff_off=v2 一键全关影响。
 * ff_ops_monitor 默认 true（Ops Monitor 作为默认首页）。
 */
export const V2_FLAGS = {
  ff_taskdrawer_smart_icon: { default: true, killable: true, task: 'V2-T2' },
  ff_taskdrawer_auto_open: { default: true, killable: true, task: 'V2-T3' },
  ff_ops_monitor: { default: true, killable: true, task: 'V2-T4' },
  ff_ops_monitor_polling: { default: true, killable: true, task: 'V2-T5' },
  ff_ops_monitor_alert_bar: { default: true, killable: true, task: 'V2-T6' },
  ff_ops_monitor_csv_export: { default: true, killable: true, task: 'V2-T7' },
  ff_redesign_sidebar: { default: true, killable: true, task: 'V3-T1' },
  ff_redesign_ops: { default: true, killable: true, task: 'V3-T2' },
  ff_redesign_today: { default: true, killable: true, task: 'V3-T3' },
  ff_drilldown_v2: { default: true, killable: true, task: 'V3-T4' },
} as const satisfies Record<string, FlagDefinition>

export const ALL_FLAGS = { ...V1_FLAGS, ...V2_FLAGS }
export type FlagKey = keyof typeof ALL_FLAGS

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

function isKillSwitchActive(sources: FlagOverrideSources, version: 'v1' | 'v2' = 'v1'): boolean {
  const { urlParams, localStorage } = sources
  const fromUrl = urlParams?.get('ff_off')?.trim().toLowerCase()
  const fromLs = localStorage?.getItem('ff_off')?.trim().toLowerCase()
  const active = fromUrl || fromLs
  if (!active) return false
  // ff_off=v1 关闭 V1 flags；ff_off=v2 关闭 V2 flags；ff_off=all 关闭全部
  if (active === 'all') return true
  return active === version
}

/**
 * 评估一个 flag 的最终值。纯函数，无副作用。
 *
 * @param key Flag 名（必须在 V1_FLAGS 中注册）
 * @param sources 三层 override 输入源
 * @returns 最终生效的 boolean 值
 */
export function evaluateFlag(key: FlagKey, sources: FlagOverrideSources): boolean {
  const def = ALL_FLAGS[key]
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
  // V2 flags 受 ff_off=v2 影响；V1 flags 受 ff_off=v1 影响
  const isV2 = key in V2_FLAGS
  if (def.killable && isKillSwitchActive(sources, isV2 ? 'v2' : 'v1')) {
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
  for (const k of Object.keys(ALL_FLAGS) as FlagKey[]) {
    out[k] = isEnabled(k)
  }
  return out as Record<FlagKey, boolean>
}

// 暴露到 window 方便手动调试（不影响生产构建尺寸）
if (typeof window !== 'undefined') {
  ;(window as unknown as { __momoFlags?: () => Record<FlagKey, boolean> }).__momoFlags = snapshotFlags
}
