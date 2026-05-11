/**
 * components/ops/OpsSettingsPopover.tsx — Spec §3.4 顶部设置 popover。
 *
 * 收纳：时间窗口 / 轮询间隔 / 静音 / CSV 导出。
 */
import { Settings, Bell, BellOff, Download } from 'lucide-react'
import { usePopover } from '../../hooks/usePopover'
import type { OpsStatsResponse } from '../../api/types'
import { opsDataToCsv } from '../../utils/opsCsv'

const TIME_WINDOWS = [
  { label: '15 分钟', value: '15m' },
  { label: '1 小时', value: '1h' },
  { label: '24 小时', value: '24h' },
] as const

const POLL_INTERVALS = [
  { label: '5s', value: 5000 },
  { label: '10s', value: 10000 },
  { label: '30s', value: 30000 },
] as const

export default function OpsSettingsPopover({
  timeWindow,
  onTimeWindowChange,
  pollInterval,
  onPollIntervalChange,
  muted,
  onMutedChange,
  data,
}: {
  timeWindow: string
  onTimeWindowChange: (v: string) => void
  pollInterval: number
  onPollIntervalChange: (v: number) => void
  muted: boolean
  onMutedChange: (v: boolean) => void
  data: OpsStatsResponse | undefined
}) {
  const { open, ref, toggle } = usePopover()

  const handleExport = () => {
    if (!data) return
    const csv = opsDataToCsv(data)
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `ops-monitor-${new Date().toISOString().slice(0, 19)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={toggle}
        className="flex items-center gap-1.5 px-3 py-2 rounded-button border border-border-default hover:bg-surface-hover text-sm text-text-secondary"
        title="设置"
      >
        <Settings size={14} />
        设置
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-2 w-64 bg-surface-card rounded-card shadow-card border border-border-default p-4 z-50">
          {/* 时间窗口 */}
          <Section label="时间窗口">
            <RadioGroup
              options={TIME_WINDOWS}
              value={timeWindow}
              onChange={onTimeWindowChange}
            />
          </Section>

          {/* 轮询间隔 */}
          <Section label="轮询间隔">
            <RadioGroup
              options={POLL_INTERVALS}
              value={pollInterval}
              onChange={onPollIntervalChange}
            />
          </Section>

          {/* 静音 */}
          <div className="flex items-center justify-between py-2 border-t border-border-soft">
            <label className="text-sm text-text-primary flex items-center gap-2">
              {muted ? <BellOff size={14} /> : <Bell size={14} />}
              静音模式
            </label>
            <button
              onClick={() => onMutedChange(!muted)}
              className={`relative w-9 h-5 rounded-pill transition-colors ${muted ? 'bg-accent' : 'bg-border-default'}`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-pill transition-transform ${muted ? 'translate-x-4' : ''}`}
              />
            </button>
          </div>

          {/* 导出 */}
          <button
            onClick={handleExport}
            disabled={!data}
            className="flex items-center justify-center gap-1.5 w-full mt-3 py-2 rounded-button bg-accent-soft text-accent-hover hover:bg-accent hover:text-white text-sm font-medium transition-colors disabled:opacity-50"
          >
            <Download size={14} />
            导出当前视图 CSV
          </button>
        </div>
      )}
    </div>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <div className="text-xs text-text-muted mb-1">{label}</div>
      {children}
    </div>
  )
}

function RadioGroup<T extends string | number>({
  options,
  value,
  onChange,
}: {
  options: readonly { label: string; value: T }[]
  value: T
  onChange: (v: T) => void
}) {
  return (
    <div className="flex gap-1">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`flex-1 px-2 py-1 rounded-pill text-xs font-medium transition-colors ${
            o.value === value
              ? 'bg-accent text-white'
              : 'bg-surface-hover text-text-secondary hover:bg-border-default'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
