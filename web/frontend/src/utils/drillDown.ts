/**
 * utils/drillDown.ts — OpsMonitor → Today 的 drill-down 上下文。
 * Spec §3.5。
 */
export interface DrillDownParams {
  errorType: string | null
  window: string | null
}

export function parseDrillDownParams(params: URLSearchParams): DrillDownParams {
  return {
    errorType: params.get('error_type'),
    window: params.get('window'),
  }
}

export function isDrillDownActive(d: DrillDownParams): boolean {
  return d.errorType != null && d.errorType !== ''
}

export function drillDownLabel(d: DrillDownParams): string {
  if (!d.errorType) return ''
  return d.window ? `${d.errorType} 错误 · ${d.window}` : `${d.errorType} 错误`
}
