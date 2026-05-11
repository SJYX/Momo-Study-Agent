/**
 * drillDown.test.ts — Drill-down URL 参数解析纯函数测试。
 */
import { describe, expect, it } from 'vitest'
import { parseDrillDownParams, isDrillDownActive, drillDownLabel } from './drillDown'

describe('parseDrillDownParams', () => {
  it('两参齐全', () => {
    const p = new URLSearchParams('error_type=AIError&window=1h')
    expect(parseDrillDownParams(p)).toEqual({ errorType: 'AIError', window: '1h' })
  })

  it('缺 window', () => {
    const p = new URLSearchParams('error_type=AIError')
    expect(parseDrillDownParams(p)).toEqual({ errorType: 'AIError', window: null })
  })

  it('无参数', () => {
    const p = new URLSearchParams('')
    expect(parseDrillDownParams(p)).toEqual({ errorType: null, window: null })
  })

  it('URL encoded', () => {
    const p = new URLSearchParams('error_type=Rate%20Limit&window=24h')
    expect(parseDrillDownParams(p)).toEqual({ errorType: 'Rate Limit', window: '24h' })
  })
})

describe('isDrillDownActive', () => {
  it('errorType 存在视为 active', () => {
    expect(isDrillDownActive({ errorType: 'X', window: null })).toBe(true)
  })
  it('errorType 缺失视为 inactive', () => {
    expect(isDrillDownActive({ errorType: null, window: '1h' })).toBe(false)
  })
})

describe('drillDownLabel', () => {
  it('两参齐全', () => {
    expect(drillDownLabel({ errorType: 'AIError', window: '1h' })).toBe('AIError 错误 · 1h')
  })
  it('只有 errorType', () => {
    expect(drillDownLabel({ errorType: 'AIError', window: null })).toBe('AIError 错误')
  })
})
