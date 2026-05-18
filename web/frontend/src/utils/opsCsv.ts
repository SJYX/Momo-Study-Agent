/**
 * utils/opsCsv.ts — Ops Monitor CSV 导出纯函数。
 */
import type { OpsStatsResponse } from '../api/types'

/**
 * 将 OpsStatsResponse 转换为 CSV 字符串。
 * 仅导出当前视图数据，不泄露无关数据。
 */
export function opsDataToCsv(data: OpsStatsResponse): string {
  const rows: string[][] = [
    ['类别', '指标', '值'],
    ['任务', '运行中', String(data.tasks_running ?? 0)],
    ['任务', '近完成', String(data.tasks_done_1h ?? 0)],
    ['任务', '近错误', String(data.tasks_error_1h ?? 0)],
    ['队列', '同步队列', String(data.sync_queue_depth ?? 0)],
    ['队列', '冲突数', String(data.sync_conflict_count ?? 0)],
    ['队列', '平均延迟', `${data.avg_latency_ms ?? 0}ms`],
    ['健康', '系统状态', data.system_ok ? '正常' : '异常'],
  ]

  for (const h of data.failure_hotspots ?? []) {
    rows.push(['失败热点', h.error_type, String(h.count)])
  }

  return rows.map(r => r.map(c => `"${c}"`).join(',')).join('\n')
}
