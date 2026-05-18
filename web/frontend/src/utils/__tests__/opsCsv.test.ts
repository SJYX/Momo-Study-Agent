/**
 * opsCsv.test.ts — Ops Monitor CSV 导出纯函数单测。
 */
import { describe, expect, it } from 'vitest'
import { opsDataToCsv } from '../opsCsv'
import type { OpsStatsResponse } from '../../api/types'

describe('opsDataToCsv', () => {
  it('基本数据导出正确', () => {
    const data: OpsStatsResponse = {
      tasks_running: 2,
      tasks_done_1h: 10,
      tasks_error_1h: 1,
      system_ok: true,
      sync_queue_depth: 5,
      sync_conflict_count: 0,
      avg_latency_ms: 123.4,
      failure_hotspots: [],
    }
    const csv = opsDataToCsv(data)
    const lines = csv.split('\n')
    expect(lines[0]).toBe('"类别","指标","值"')
    expect(lines).toContain('"任务","运行中","2"')
    expect(lines).toContain('"任务","近完成","10"')
    expect(lines).toContain('"任务","近错误","1"')
    expect(lines).toContain('"健康","系统状态","正常"')
    expect(lines).toContain('"队列","同步队列","5"')
    expect(lines).toContain('"队列","平均延迟","123.4ms"')
  })

  it('系统异常时显示异常', () => {
    const data: OpsStatsResponse = { system_ok: false }
    const csv = opsDataToCsv(data)
    expect(csv).toContain('"健康","系统状态","异常"')
  })

  it('失败热点导出', () => {
    const data: OpsStatsResponse = {
      failure_hotspots: [
        { error_type: 'ai_batch_error', count: 5 },
        { error_type: 'timeout', error_code: 'E001', count: 3 },
      ],
    }
    const csv = opsDataToCsv(data)
    expect(csv).toContain('"失败热点","ai_batch_error","5"')
    expect(csv).toContain('"失败热点","timeout","3"')
  })

  it('空数据不崩溃', () => {
    const data: OpsStatsResponse = {}
    const csv = opsDataToCsv(data)
    expect(csv).toContain('"任务","运行中","0"')
    // system_ok 未定义时显示异常（安全默认值）
    expect(csv).toContain('"健康","系统状态","异常"')
  })
})
