/**
 * featureFlags.test.ts — V1 Feature Flag 评估纯函数单测。
 *
 * 覆盖范围：
 *   1. 默认值（无任何 override）
 *   2. URL 参数覆盖
 *   3. localStorage 覆盖
 *   4. 环境变量覆盖
 *   5. 一键全关 ff_off=v1（killable / non-killable 区分）
 *   6. per-flag override 优先级高于 kill switch
 *   7. 真假值的多种字面量
 *   8. 未注册 flag 返回 false
 */
import { describe, expect, it } from 'vitest'
import { evaluateFlag, V1_FLAGS, BULK_RETRY_THRESHOLD } from './featureFlags'
import type { FlagKey, FlagOverrideSources } from './featureFlags'

function makeLs(map: Record<string, string>) {
  return { getItem: (k: string) => (k in map ? map[k] : null) }
}

describe('featureFlags', () => {
  it('默认值：未配置任何 override 时使用 registry default', () => {
    const sources: FlagOverrideSources = {}
    expect(evaluateFlag('ff_today_default_view', sources)).toBe(false)
    expect(evaluateFlag('ff_today_bulk_guard', sources)).toBe(true)
  })

  it('URL 参数：?ff_xxx=on 强制打开', () => {
    const sources: FlagOverrideSources = {
      urlParams: new URLSearchParams('?ff_today_default_view=on'),
    }
    expect(evaluateFlag('ff_today_default_view', sources)).toBe(true)
  })

  it('URL 参数：?ff_xxx=off 强制关闭（覆盖 default true 的 flag）', () => {
    const sources: FlagOverrideSources = {
      urlParams: new URLSearchParams('?ff_today_bulk_guard=off'),
    }
    expect(evaluateFlag('ff_today_bulk_guard', sources)).toBe(false)
  })

  it('localStorage 覆盖：当 URL 不存在时生效', () => {
    const sources: FlagOverrideSources = {
      localStorage: makeLs({ ff_today_failure_groups: 'on' }),
    }
    expect(evaluateFlag('ff_today_failure_groups', sources)).toBe(true)
  })

  it('优先级：URL 高于 localStorage', () => {
    const sources: FlagOverrideSources = {
      urlParams: new URLSearchParams('?ff_today_failure_groups=off'),
      localStorage: makeLs({ ff_today_failure_groups: 'on' }),
    }
    expect(evaluateFlag('ff_today_failure_groups', sources)).toBe(false)
  })

  it('一键全关 URL：?ff_off=v1 关闭所有 killable flag', () => {
    const sources: FlagOverrideSources = {
      urlParams: new URLSearchParams('?ff_off=v1'),
    }
    expect(evaluateFlag('ff_today_default_view', sources)).toBe(false)
    expect(evaluateFlag('ff_today_failure_groups', sources)).toBe(false)
    expect(evaluateFlag('ff_today_group_retry', sources)).toBe(false)
  })

  it('一键全关：bulk_guard 是 non-killable，仍保持默认 ON', () => {
    const sources: FlagOverrideSources = {
      urlParams: new URLSearchParams('?ff_off=v1'),
    }
    expect(evaluateFlag('ff_today_bulk_guard', sources)).toBe(true)
  })

  it('一键全关 localStorage：ff_off=v1 等价于 URL 形式', () => {
    const sources: FlagOverrideSources = {
      localStorage: makeLs({ ff_off: 'v1' }),
    }
    expect(evaluateFlag('ff_today_default_view', sources)).toBe(false)
    expect(evaluateFlag('ff_today_bulk_guard', sources)).toBe(true)
  })

  it('per-flag URL override 优先级高于 kill switch', () => {
    const sources: FlagOverrideSources = {
      urlParams: new URLSearchParams('?ff_off=v1&ff_today_default_view=on'),
    }
    // kill switch 应该被 per-flag override 推翻
    expect(evaluateFlag('ff_today_default_view', sources)).toBe(true)
    // 其他 killable flag 仍然被 kill 关闭
    expect(evaluateFlag('ff_today_failure_groups', sources)).toBe(false)
  })

  it('per-flag localStorage override 优先级高于 kill switch', () => {
    const sources: FlagOverrideSources = {
      urlParams: new URLSearchParams('?ff_off=v1'),
      localStorage: makeLs({ ff_today_summary_stay: 'on' }),
    }
    expect(evaluateFlag('ff_today_summary_stay', sources)).toBe(true)
  })

  it('环境变量覆盖：仅在 URL/LS 都不存在时生效', () => {
    const sources: FlagOverrideSources = {
      env: { VITE_FF_TODAY_LIGHT_CONFIRM: 'on' },
    }
    expect(evaluateFlag('ff_today_light_confirm', sources)).toBe(true)
  })

  it('环境变量优先级：低于 localStorage', () => {
    const sources: FlagOverrideSources = {
      localStorage: makeLs({ ff_today_light_confirm: 'off' }),
      env: { VITE_FF_TODAY_LIGHT_CONFIRM: 'on' },
    }
    expect(evaluateFlag('ff_today_light_confirm', sources)).toBe(false)
  })

  it('真值字面量：on/true/1/yes 都视为 true', () => {
    for (const v of ['on', 'true', '1', 'yes', 'ON', 'TRUE']) {
      const sources: FlagOverrideSources = {
        urlParams: new URLSearchParams(`?ff_today_default_view=${v}`),
      }
      expect(evaluateFlag('ff_today_default_view', sources)).toBe(true)
    }
  })

  it('假值字面量：off/false/0/no 都视为 false', () => {
    for (const v of ['off', 'false', '0', 'no', 'OFF', 'FALSE']) {
      const sources: FlagOverrideSources = {
        urlParams: new URLSearchParams(`?ff_today_bulk_guard=${v}`),
      }
      expect(evaluateFlag('ff_today_bulk_guard', sources)).toBe(false)
    }
  })

  it('无效字面量退回到下一层（lower priority）', () => {
    const sources: FlagOverrideSources = {
      urlParams: new URLSearchParams('?ff_today_default_view=garbage'),
      localStorage: makeLs({ ff_today_default_view: 'on' }),
    }
    expect(evaluateFlag('ff_today_default_view', sources)).toBe(true)
  })

  it('未注册 flag：返回 false 防止静默放行', () => {
    const sources: FlagOverrideSources = {}
    // 强制类型转换以模拟拼写错误的场景
    expect(evaluateFlag('ff_unknown' as unknown as FlagKey, sources)).toBe(false)
  })

  it('V1_FLAGS 注册表：所有 V1 flag 都有 task 标记', () => {
    for (const [key, def] of Object.entries(V1_FLAGS)) {
      expect(def.task).toMatch(/^T\d/)
      expect(typeof def.default).toBe('boolean')
      expect(typeof def.killable).toBe('boolean')
      // 安全护栏 flag 必须 non-killable
      if (key === 'ff_today_bulk_guard') {
        expect(def.killable).toBe(false)
      }
    }
  })

  it('BULK_RETRY_THRESHOLD：与 C03 §3 一致', () => {
    expect(BULK_RETRY_THRESHOLD).toBe(100)
  })
})
