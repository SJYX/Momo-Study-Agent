# Web UI 改版实施计划 · OpsMonitor + TodayTasks + Sidebar

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Web UI 三处（左侧 Sidebar / OpsMonitor 监控台 / TodayTasks 今日任务）的视觉与局部交互重做为暖色 Notion 风，每个改动用 feature flag 保护、可一键回退。

**Architecture:** Tailwind v4 `@theme` 声明 CSS 变量层；每个改造的页面/组件保留旧版本，在文件顶部根据 feature flag 分发到 V2 版本——这样无 regression 风险，主分支默认 off，用户单独开启。所有现有 hooks / stores / queries / 状态机一律不动。

**Tech Stack:** React 18.3 · TypeScript 5.6 · Tailwind v4（CSS-first config）· Tanstack Query 5 · Zustand 5 · React Router 6 · vitest 2 + jsdom 25 · lucide-react · 无 popover 库（自行实现）

**Spec:** [`docs/superpowers/specs/2026-05-11-web-ui-redesign-ops-and-today-design.md`](../specs/2026-05-11-web-ui-redesign-ops-and-today-design.md)

---

## Pre-flight: 环境就绪检查

确认在正确分支 + 现有测试通过 + 开发服务器能跑。

- [ ] **Step P.1: 确认分支**

  Run: `git branch --show-current`
  Expected: `feat/web-ui`（或在其之上的 feature 分支）

  若不是，新建一个分支：`git checkout -b feat/web-ui-redesign`

- [ ] **Step P.2: 跑现有前端测试**

  Run: `cd web/frontend && npm test`
  Expected: 全部测试通过（vitest run）

- [ ] **Step P.3: 跑一次 build 确认没有现存问题**

  Run: `cd web/frontend && npm run build`
  Expected: `vite build` 成功，无 TS 错误

- [ ] **Step P.4: （手动）启动开发服 confirm 当前 UI 能跑**

  Run: `python scripts/start_web.py --dev --user <username>`
  浏览器打开 `http://localhost:5173`，确认 Today / OpsMonitor 两页可见。Ctrl+C 停止。

---

## Task 1: Design Tokens（Spec §1，Step 1）

把整套色板/字号/圆角/阴影通过 Tailwind v4 `@theme` 落到 `src/index.css`。**无 feature flag**——只添加 token 不破坏任何现有组件（它们仍用 `bg-gray-50` 等旧 class）。

**Files:**
- Modify: `web/frontend/src/index.css`

- [ ] **Step 1.1: 写入新 `@theme` 块**

  替换文件全文为：

  ```css
  @import "tailwindcss";

  @theme {
    /* === Surface（背景层）=== */
    --color-surface-base: #FAF8F3;
    --color-surface-card: #FFFFFF;
    --color-surface-sidebar: #F4ECDD;
    --color-surface-hover: #F1ECE3;
    --color-surface-highlight: #FCEFE5;

    /* === Border === */
    --color-border-default: #E9E0CD;
    --color-border-soft: #F1ECE3;
    --color-border-hero: #F4E1D2;

    /* === Text === */
    --color-text-primary: #37352F;
    --color-text-secondary: #6B5D45;
    --color-text-muted: #908A7F;

    /* === Accent（暖橙）=== */
    --color-accent: #D97757;
    --color-accent-hover: #B85433;
    --color-accent-soft: rgba(217, 119, 87, 0.15);

    /* === Error === */
    --color-error: #B43421;
    --color-error-soft: #FDE7E3;

    /* === Radius === */
    --radius-pill: 6px;
    --radius-button: 8px;
    --radius-card: 12px;

    /* === Shadow === */
    --shadow-card: 0 1px 3px rgba(15, 15, 15, 0.04);
    --shadow-hero: 0 2px 8px rgba(217, 119, 87, 0.08);
  }
  ```

- [ ] **Step 1.2: 跑 build 确认 token 被识别**

  Run: `cd web/frontend && npm run build`
  Expected: 构建成功；如果 Tailwind 报警告说 `@theme` 不识别，说明 Tailwind 版本不对——检查 `package.json` 中 `tailwindcss` 是否 `^4.x`。

- [ ] **Step 1.3: 在一个无关组件里临时用一下 token 类做 smoke test**

  改 `web/frontend/src/App.tsx`：把 `bg-gray-50` 改成 `bg-surface-base`。
  Run: `npm run dev`，浏览器看背景色应该变成米白 #FAF8F3 而不是浅灰。
  确认后 **改回 `bg-gray-50`**——本期不动 App.tsx 这种全局 chrome 文件。

- [ ] **Step 1.4: 提交**

  ```bash
  git add web/frontend/src/index.css
  git commit -m "feat(web/ui): add design tokens for warm Notion redesign

  Tailwind v4 @theme block: surface/border/text/accent/error colors,
  pill/button/card radius, card/hero shadow. No component changes yet.

  Spec §1."
  ```

---

## Task 2: Sidebar 暖调换皮（Spec §2，Step 2）

注册 `ff_redesign_sidebar` flag，把 Sidebar 拆出 V2 版本，在 `Sidebar.tsx` 顶部按 flag 分发。

**Files:**
- Modify: `web/frontend/src/utils/featureFlags.ts`
- Modify: `web/frontend/src/utils/featureFlags.test.ts`
- Create: `web/frontend/src/components/layout/SidebarV2.tsx`
- Modify: `web/frontend/src/components/layout/Sidebar.tsx`

### 2A. 注册 feature flag

- [ ] **Step 2.1: 写失败测试（flag 默认值）**

  打开 `web/frontend/src/utils/featureFlags.test.ts`，找到最后一个 `it(...)`，**在 `describe` 结束 `})` 前**追加：

  ```typescript
  it('redesign flags：默认 off', () => {
    const sources: FlagOverrideSources = {}
    expect(evaluateFlag('ff_redesign_sidebar', sources)).toBe(false)
    expect(evaluateFlag('ff_redesign_ops', sources)).toBe(false)
    expect(evaluateFlag('ff_redesign_today', sources)).toBe(false)
    expect(evaluateFlag('ff_drilldown_v2', sources)).toBe(false)
  })
  ```

- [ ] **Step 2.2: 跑测试确认失败**

  Run: `cd web/frontend && npx vitest run src/utils/featureFlags.test.ts`
  Expected: 该用例 FAIL，TS 也会报 `'ff_redesign_sidebar' is not assignable to FlagKey`。

- [ ] **Step 2.3: 在 V2_FLAGS 里注册 4 个 redesign flag**

  打开 `web/frontend/src/utils/featureFlags.ts`，找到 `V2_FLAGS` 定义末尾，在闭合 `}` 之前追加 4 行：

  ```typescript
  ff_redesign_sidebar: { default: false, killable: true, task: 'V3-T1' },
  ff_redesign_ops: { default: false, killable: true, task: 'V3-T2' },
  ff_redesign_today: { default: false, killable: true, task: 'V3-T3' },
  ff_drilldown_v2: { default: false, killable: true, task: 'V3-T4' },
  ```

- [ ] **Step 2.4: 跑测试确认通过**

  Run: `cd web/frontend && npx vitest run src/utils/featureFlags.test.ts`
  Expected: PASS

- [ ] **Step 2.5: 提交 flag 注册**

  ```bash
  git add web/frontend/src/utils/featureFlags.ts web/frontend/src/utils/featureFlags.test.ts
  git commit -m "feat(web/ui): register 4 redesign feature flags (default off)

  ff_redesign_sidebar / ff_redesign_ops / ff_redesign_today / ff_drilldown_v2.
  All killable; can be turned on individually via URL or localStorage.

  Spec §7."
  ```

### 2B. 实现 SidebarV2

- [ ] **Step 2.6: 创建 SidebarV2.tsx**

  Create `web/frontend/src/components/layout/SidebarV2.tsx`：

  ```typescript
  /**
   * components/layout/SidebarV2.tsx — 暖色 Notion 风 Sidebar 重写。
   * 受 ff_redesign_sidebar 控制，由 Sidebar.tsx 分发。
   */
  import { NavLink, useNavigate } from 'react-router-dom'
  import { useQueryClient } from '@tanstack/react-query'
  import {
    Activity, LayoutDashboard, BookOpen, CalendarDays, RefreshCw,
    Library, RefreshCcw, Shield, Users, LogOut,
  } from 'lucide-react'
  import { useProfileStore } from '../../stores/profile'
  import { isEnabled } from '../../utils/featureFlags'
  import { prefetchForRoute } from '../../queries/prefetch'

  const navItems = isEnabled('ff_ops_monitor')
    ? [
        { to: '/', label: '运维监控', icon: Activity },
        { to: '/today', label: '今日任务', icon: BookOpen },
        { to: '/future', label: '未来计划', icon: CalendarDays },
        { to: '/iteration', label: '智能迭代', icon: RefreshCw },
        { to: '/words', label: '单词库', icon: Library },
        { to: '/sync', label: '同步状态', icon: RefreshCcw },
        { to: '/preflight', label: '体检', icon: Shield },
        { to: '/dashboard', label: '仪表盘', icon: LayoutDashboard },
        { to: '/users', label: '用户设置', icon: Users },
      ]
    : [
        { to: '/', label: '仪表盘', icon: LayoutDashboard },
        { to: '/today', label: '今日任务', icon: BookOpen },
        { to: '/future', label: '未来计划', icon: CalendarDays },
        { to: '/iteration', label: '智能迭代', icon: RefreshCw },
        { to: '/words', label: '单词库', icon: Library },
        { to: '/sync', label: '同步状态', icon: RefreshCcw },
        { to: '/preflight', label: '体检', icon: Shield },
        { to: '/users', label: '用户设置', icon: Users },
      ]

  export default function SidebarV2() {
    const activeProfile = useProfileStore((s) => s.activeProfile)
    const clearProfile = useProfileStore((s) => s.clearProfile)
    const navigate = useNavigate()
    const queryClient = useQueryClient()

    const handleSwitchProfile = () => {
      clearProfile()
      navigate('/gateway', { replace: true })
    }

    return (
      <aside className="w-56 bg-surface-sidebar text-text-secondary flex flex-col min-h-screen border-r border-border-default">
        {/* Logo */}
        <div className="px-4 py-5 border-b border-border-default">
          <h1 className="text-lg font-bold tracking-tight text-text-primary">MOMO Agent</h1>
          <p className="text-xs text-text-muted mt-0.5">智能单词助记系统</p>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-2 py-3 space-y-0.5">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onMouseEnter={() => prefetchForRoute(queryClient, to)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-button text-sm transition-colors ${
                  isActive
                    ? 'bg-accent-soft text-accent-hover font-semibold'
                    : 'text-text-secondary hover:bg-surface-hover hover:text-text-primary'
                }`
              }
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Profile + Footer */}
        <div className="px-4 py-3 border-t border-border-default">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-text-muted truncate">{activeProfile || '未选择'}</span>
            <button
              onClick={handleSwitchProfile}
              className="text-text-muted hover:text-text-primary transition-colors"
              title="切换 Profile"
            >
              <LogOut size={14} />
            </button>
          </div>
          <div className="text-xs text-text-muted opacity-60">v1.0.0</div>
        </div>
      </aside>
    )
  }
  ```

- [ ] **Step 2.7: 在 Sidebar.tsx 顶部加 flag dispatch**

  打开 `web/frontend/src/components/layout/Sidebar.tsx`，在 `export default function Sidebar() {` 的第一行**之前**插入：

  ```typescript
  import { isEnabled } from '../../utils/featureFlags'
  import SidebarV2 from './SidebarV2'
  ```

  然后在 `Sidebar` 函数体的最开头（return 之前的所有 useXxx 之前）插入：

  ```typescript
    if (isEnabled('ff_redesign_sidebar')) return <SidebarV2 />
  ```

  **注意**：原 `Sidebar` 内的 `useProfileStore` / `useNavigate` / `useQueryClient` 调用必须保留（不能放到 if 之后）——但因为 `if` 在最前面 return，剩余 hooks 不会被调用。这违反 React Hooks 规则。正确的做法是 SidebarV2 不复用 Sidebar 的 hooks，所以可以直接 early-return；但我们要把 `if` 放在所有 hook 之前。

  覆盖整个 `Sidebar` 函数为：

  ```typescript
  export default function Sidebar() {
    if (isEnabled('ff_redesign_sidebar')) return <SidebarV2 />

    const activeProfile = useProfileStore((s) => s.activeProfile)
    const clearProfile = useProfileStore((s) => s.clearProfile)
    const navigate = useNavigate()
    const queryClient = useQueryClient()

    const handleSwitchProfile = () => {
      clearProfile()
      navigate('/gateway', { replace: true })
    }

    // ...其余 return JSX 保持不变...
  }
  ```

  **说明**：React Hooks 规则要求 hooks 数量在每次渲染中固定。这里 flag 在生命周期内不变（来自 URL/localStorage，需要刷新才生效），所以两个 branch 的 hook 数量稳定，符合规则。Lint 可能仍报警告，加 `// eslint-disable-next-line react-hooks/rules-of-hooks` 即可。

- [ ] **Step 2.8: 跑 build 确认 TypeScript 通过**

  Run: `cd web/frontend && npm run build`
  Expected: 构建成功。

- [ ] **Step 2.9: 手动验证（dev server）**

  Run: `python scripts/start_web.py --dev --user <username>`
  浏览器：
  - 默认进入：sidebar 仍是 **旧版深色**（flag 默认 off）
  - URL 末尾加 `?ff_redesign_sidebar=on` 刷新：sidebar 应变成 **米色**，active 项暖橙
  - 切换 nav 项、切 profile，行为不变
  - 控制台 `__momoFlags()` 看 `ff_redesign_sidebar: true`

- [ ] **Step 2.10: 提交**

  ```bash
  git add web/frontend/src/components/layout/SidebarV2.tsx \
          web/frontend/src/components/layout/Sidebar.tsx
  git commit -m "feat(web/ui): SidebarV2 in warm Notion palette behind ff_redesign_sidebar

  Side rail switches to #F4ECDD background, accent-soft active state,
  text-secondary defaults. Default off; toggle with ?ff_redesign_sidebar=on.

  Spec §2."
  ```

---

## Task 3: OpsMonitor V2（Spec §3，Step 3）

新建 5 个 ops 子组件 + 1 个 popover hook + V2 页面，在 `OpsMonitor.tsx` 顶部按 `ff_redesign_ops` 分发。

**Files:**
- Create: `web/frontend/src/hooks/usePopover.ts`
- Create: `web/frontend/src/hooks/usePopover.test.ts`
- Create: `web/frontend/src/components/ops/OpsHero.tsx`
- Create: `web/frontend/src/components/ops/OpsSettingsPopover.tsx`
- Create: `web/frontend/src/components/ops/FailureHotspotsCard.tsx`
- Create: `web/frontend/src/components/ops/SystemHealthCard.tsx`
- Create: `web/frontend/src/components/ops/QueueLatencyCard.tsx`
- Create: `web/frontend/src/pages/OpsMonitorV2.tsx`
- Modify: `web/frontend/src/pages/OpsMonitor.tsx`

### 3A. usePopover hook

- [ ] **Step 3.1: 写失败测试**

  Create `web/frontend/src/hooks/usePopover.test.ts`：

  ```typescript
  /**
   * usePopover.test.ts — 自管 outside-click + Escape 的轻量 popover 状态钩子。
   */
  import { describe, expect, it } from 'vitest'
  import { renderHook, act } from '@testing-library/react'
  import { usePopover } from './usePopover'

  describe('usePopover', () => {
    it('toggle 切换 open 状态', () => {
      const { result } = renderHook(() => usePopover())
      expect(result.current.open).toBe(false)
      act(() => result.current.toggle())
      expect(result.current.open).toBe(true)
      act(() => result.current.toggle())
      expect(result.current.open).toBe(false)
    })

    it('close 强制关闭', () => {
      const { result } = renderHook(() => usePopover())
      act(() => result.current.toggle())
      expect(result.current.open).toBe(true)
      act(() => result.current.close())
      expect(result.current.open).toBe(false)
    })

    it('Escape 键关闭 open popover', () => {
      const { result } = renderHook(() => usePopover())
      act(() => result.current.toggle())
      expect(result.current.open).toBe(true)
      act(() => {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
      })
      expect(result.current.open).toBe(false)
    })

    it('关闭状态下 Escape 不影响', () => {
      const { result } = renderHook(() => usePopover())
      act(() => {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
      })
      expect(result.current.open).toBe(false)
    })
  })
  ```

- [ ] **Step 3.2: 跑测试确认失败（模块不存在 / 环境不对）**

  Run: `cd web/frontend && npx vitest run src/hooks/usePopover.test.ts`
  Expected: FAIL，找不到 `./usePopover`、缺 `@testing-library/react`、且 `document is not defined`（vitest 默认 `environment: 'node'`）。

- [ ] **Step 3.3: 安装 @testing-library/react 并切换 vitest 到 jsdom 环境**

  Run: `cd web/frontend && npm install --save-dev @testing-library/react @testing-library/dom`
  Expected: 安装成功。

  打开 `web/frontend/vite.config.ts`，把 `test` 块改为：

  ```typescript
    test: {
      // 同时支持纯函数测试（默认 jsdom 也兼容）和组件 / DOM 事件测试
      environment: 'jsdom',
      include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
      globals: false,
    },
  ```

  Run: `cd web/frontend && npx vitest run`
  Expected: 原有测试仍然 PASS（jsdom 是 node 超集，纯函数测试不受影响）；usePopover 测试此时还是 FAIL（实现未写）。

- [ ] **Step 3.4: 实现 usePopover**

  Create `web/frontend/src/hooks/usePopover.ts`：

  ```typescript
  /**
   * hooks/usePopover.ts — 轻量 popover 状态管理。
   *
   * 提供 open 状态 + toggle/close 方法 + 自动 outside-click/Escape 关闭。
   * ref 由调用方挂到 popover 根元素上。
   *
   * 项目没有 Radix / Headless UI，先用这个最小实现；后续可平替为
   * @radix-ui/react-popover（API 类似）。
   */
  import { useCallback, useEffect, useRef, useState } from 'react'

  export interface PopoverState {
    open: boolean
    ref: React.RefObject<HTMLDivElement>
    toggle: () => void
    close: () => void
  }

  export function usePopover(): PopoverState {
    const [open, setOpen] = useState(false)
    const ref = useRef<HTMLDivElement>(null)

    const toggle = useCallback(() => setOpen((v) => !v), [])
    const close = useCallback(() => setOpen(false), [])

    useEffect(() => {
      if (!open) return
      const onDown = (e: MouseEvent) => {
        if (ref.current && !ref.current.contains(e.target as Node)) {
          setOpen(false)
        }
      }
      const onKey = (e: KeyboardEvent) => {
        if (e.key === 'Escape') setOpen(false)
      }
      document.addEventListener('mousedown', onDown)
      document.addEventListener('keydown', onKey)
      return () => {
        document.removeEventListener('mousedown', onDown)
        document.removeEventListener('keydown', onKey)
      }
    }, [open])

    return { open, ref, toggle, close }
  }
  ```

- [ ] **Step 3.5: 跑测试确认通过**

  Run: `cd web/frontend && npx vitest run src/hooks/usePopover.test.ts`
  Expected: 4 个用例 PASS。

- [ ] **Step 3.6: 提交 usePopover**

  ```bash
  git add web/frontend/package.json web/frontend/package-lock.json \
          web/frontend/vite.config.ts \
          web/frontend/src/hooks/usePopover.ts web/frontend/src/hooks/usePopover.test.ts
  git commit -m "feat(web/ui): add usePopover hook with outside-click + Escape handling

  Lightweight standalone replacement for Radix Popover. Used by
  OpsSettingsPopover.

  Test infra: switch vitest environment to jsdom (jsdom was already in
  devDeps) and add @testing-library/react to enable DOM event testing."
  ```

### 3B. Ops 子组件（5 个）

- [ ] **Step 3.7: 创建 OpsHero.tsx**

  Create `web/frontend/src/components/ops/OpsHero.tsx`：

  ```typescript
  /**
   * components/ops/OpsHero.tsx — OpsMonitor 顶部状态总览 Hero。
   * Spec §3.2。
   */
  import { useNavigate } from 'react-router-dom'
  import { Check, AlertTriangle, PlayCircle } from 'lucide-react'
  import type { OpsStatsResponse } from '../../api/types'

  const WINDOW_LABELS: Record<string, string> = {
    '15m': '最近 15 分钟',
    '1h': '最近 1 小时',
    '24h': '最近 24 小时',
  }

  export default function OpsHero({
    data,
    timeWindow,
  }: {
    data: OpsStatsResponse | undefined
    timeWindow: string
  }) {
    const navigate = useNavigate()
    const ok = data?.system_ok !== false
    const running = data?.tasks_running ?? 0
    const done = data?.tasks_done_1h ?? 0
    const errors = data?.tasks_error_1h ?? 0

    return (
      <div className="rounded-card border border-border-hero shadow-hero p-6 bg-gradient-to-br from-surface-card to-surface-highlight">
        <div className="text-xs text-text-muted mb-2">{WINDOW_LABELS[timeWindow] || timeWindow}</div>
        <div className="flex items-center gap-2 mb-4">
          {ok ? (
            <>
              <Check size={18} className="text-text-primary" />
              <span className="text-base font-semibold text-text-primary">全系统正常</span>
            </>
          ) : (
            <>
              <AlertTriangle size={18} className="text-error" />
              <span className="text-base font-semibold text-error">系统健康异常</span>
            </>
          )}
          <span className="text-xs text-text-muted ml-2">
            · {running} 项运行中 · {errors} 项错误
          </span>
        </div>
        <div className="flex items-center justify-between">
          <div className="flex gap-6">
            <Stat label="运行中" value={running} accent />
            <Stat label="已完成" value={done} />
            <Stat label="错误" value={errors} />
          </div>
          <button
            onClick={() => navigate('/today')}
            className="flex items-center gap-1.5 bg-accent hover:bg-accent-hover text-white px-4 py-2 rounded-button text-sm font-semibold transition-colors"
          >
            <PlayCircle size={16} />
            进入今日 →
          </button>
        </div>
      </div>
    )
  }

  function Stat({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
    return (
      <div>
        <div className={`text-2xl font-bold ${accent ? 'text-accent' : 'text-text-primary'}`}>{value}</div>
        <div className="text-xs text-text-muted">{label}</div>
      </div>
    )
  }
  ```

- [ ] **Step 3.8: 创建 FailureHotspotsCard.tsx**

  Create `web/frontend/src/components/ops/FailureHotspotsCard.tsx`：

  ```typescript
  /**
   * components/ops/FailureHotspotsCard.tsx — Spec §3.3 失败热点卡。
   */
  import { useState } from 'react'
  import { useNavigate } from 'react-router-dom'
  import { AlertTriangle, XCircle, ChevronDown } from 'lucide-react'
  import type { FailureHotspot } from '../../api/types'

  function formatTimeAgo(ts: number): string {
    if (!ts) return '-'
    const diff = Date.now() / 1000 - ts
    if (diff < 60) return '刚刚'
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
    return `${Math.floor(diff / 86400)} 天前`
  }

  export default function FailureHotspotsCard({
    hotspots,
    timeWindow,
  }: {
    hotspots: FailureHotspot[]
    timeWindow: string
  }) {
    const navigate = useNavigate()
    const [expanded, setExpanded] = useState(false)
    const visible = expanded ? hotspots : hotspots.slice(0, 5)

    return (
      <div className="bg-surface-card rounded-card shadow-card p-4">
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle size={16} className="text-error" />
          <h3 className="text-sm font-semibold text-text-primary">失败热点</h3>
        </div>
        {hotspots.length === 0 ? (
          <div className="text-text-muted text-sm text-center py-6">暂无失败记录</div>
        ) : (
          <div className="space-y-1">
            {visible.map((h, i) => (
              <div
                key={i}
                onClick={() =>
                  navigate(
                    `/today?error_type=${encodeURIComponent(h.error_type)}&window=${encodeURIComponent(timeWindow)}`,
                  )
                }
                className="flex items-center gap-2 text-sm py-1.5 px-2 rounded-pill hover:bg-surface-hover cursor-pointer"
              >
                <XCircle size={14} className="text-error" />
                <span className="font-medium text-text-primary">{h.error_type}</span>
                {h.error_code && <span className="text-xs text-text-muted">({h.error_code})</span>}
                <span className="text-xs text-text-muted ml-auto">{h.count} 次</span>
                <span className="text-xs text-text-muted">{formatTimeAgo(h.latest_at ?? 0)}</span>
              </div>
            ))}
            {hotspots.length > 5 && (
              <button
                onClick={() => setExpanded((v) => !v)}
                className="text-xs text-text-muted hover:text-text-primary flex items-center gap-1 mt-1"
              >
                <ChevronDown size={12} className={expanded ? 'rotate-180' : ''} />
                {expanded ? '收起' : `展开全部 (${hotspots.length})`}
              </button>
            )}
          </div>
        )}
      </div>
    )
  }
  ```

- [ ] **Step 3.9: 创建 SystemHealthCard.tsx**

  Create `web/frontend/src/components/ops/SystemHealthCard.tsx`：

  ```typescript
  /**
   * components/ops/SystemHealthCard.tsx — Spec §3.3 系统健康卡。
   */
  import { useState } from 'react'
  import { Wifi, WifiOff, CheckCircle2, XCircle, ChevronDown } from 'lucide-react'
  import type { PreflightCheck } from '../../api/types'

  export default function SystemHealthCard({
    systemOk,
    checks,
  }: {
    systemOk: boolean
    checks: PreflightCheck[]
  }) {
    const [expanded, setExpanded] = useState(false)
    const visible = expanded ? checks : checks.slice(0, 5)

    return (
      <div className="bg-surface-card rounded-card shadow-card p-4">
        <div className="flex items-center gap-2 mb-3">
          {systemOk ? (
            <Wifi size={16} className="text-text-primary" />
          ) : (
            <WifiOff size={16} className="text-error" />
          )}
          <h3 className="text-sm font-semibold text-text-primary">系统健康</h3>
          <span className={`text-xs ml-auto ${systemOk ? 'text-text-muted' : 'text-error font-medium'}`}>
            {systemOk ? '正常' : '异常'}
          </span>
        </div>
        {checks.length === 0 ? (
          <div className="text-text-muted text-sm text-center py-6">暂无检查记录</div>
        ) : (
          <div className="space-y-1">
            {visible.map((c, i) => (
              <div key={i} className="flex items-center gap-2 text-sm py-1">
                {c.ok ? (
                  <CheckCircle2 size={14} className="text-text-secondary" />
                ) : (
                  <XCircle size={14} className="text-error" />
                )}
                <span className={c.ok ? 'text-text-secondary' : 'text-error font-medium'}>{c.name}</span>
                {!c.ok && <span className="text-xs text-text-muted truncate">{c.detail}</span>}
              </div>
            ))}
            {checks.length > 5 && (
              <button
                onClick={() => setExpanded((v) => !v)}
                className="text-xs text-text-muted hover:text-text-primary flex items-center gap-1 mt-1"
              >
                <ChevronDown size={12} className={expanded ? 'rotate-180' : ''} />
                {expanded ? '收起' : `展开全部 (${checks.length})`}
              </button>
            )}
          </div>
        )}
      </div>
    )
  }
  ```

- [ ] **Step 3.10: 创建 QueueLatencyCard.tsx**

  Create `web/frontend/src/components/ops/QueueLatencyCard.tsx`：

  ```typescript
  /**
   * components/ops/QueueLatencyCard.tsx — Spec §3.3 队列与延迟卡。
   */
  import { Database } from 'lucide-react'
  import type { OpsStatsResponse } from '../../api/types'

  export default function QueueLatencyCard({ data }: { data: OpsStatsResponse | undefined }) {
    return (
      <div className="bg-surface-card rounded-card shadow-card p-4">
        <div className="flex items-center gap-2 mb-3">
          <Database size={16} className="text-text-primary" />
          <h3 className="text-sm font-semibold text-text-primary">队列与延迟</h3>
        </div>
        <div className="grid grid-cols-3 gap-3 mt-3">
          <Stat label="同步队列" value={data?.sync_queue_depth ?? 0} />
          <Stat label="冲突数" value={data?.sync_conflict_count ?? 0} accent={(data?.sync_conflict_count ?? 0) > 0} />
          <Stat label="平均延迟" value={`${data?.avg_latency_ms ?? 0}ms`} />
        </div>
      </div>
    )
  }

  function Stat({ label, value, accent }: { label: string; value: number | string; accent?: boolean }) {
    return (
      <div className="text-center">
        <div className={`text-xl font-bold ${accent ? 'text-error' : 'text-text-primary'}`}>{value}</div>
        <div className="text-[11px] text-text-muted">{label}</div>
      </div>
    )
  }
  ```

- [ ] **Step 3.11: 创建 OpsSettingsPopover.tsx**

  Create `web/frontend/src/components/ops/OpsSettingsPopover.tsx`：

  ```typescript
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
  ```

### 3C. OpsMonitorV2 页面

- [ ] **Step 3.12: 创建 OpsMonitorV2.tsx**

  Create `web/frontend/src/pages/OpsMonitorV2.tsx`：

  ```typescript
  /**
   * pages/OpsMonitorV2.tsx — OpsMonitor 重绘版本（Hero + 三卡）。
   * 数据层完全复用旧 OpsMonitor 的 useQuery；只换渲染。
   * Spec §3。
   */
  import { useState } from 'react'
  import { useNavigate } from 'react-router-dom'
  import { useQuery, useQueryClient } from '@tanstack/react-query'
  import { RefreshCw, AlertTriangle, ChevronRight, Activity, PlayCircle } from 'lucide-react'
  import { apiClient } from '../api/client'
  import { useOnActiveUserChanged } from '../hooks/useOnActiveUserChanged'
  import { useProfileStore } from '../stores/profile'
  import { isEnabled } from '../utils/featureFlags'
  import { queryKeys } from '../queries/queryClient'
  import ErrorBanner from '../components/ui/ErrorBanner'
  import OpsHero from '../components/ops/OpsHero'
  import OpsSettingsPopover from '../components/ops/OpsSettingsPopover'
  import FailureHotspotsCard from '../components/ops/FailureHotspotsCard'
  import SystemHealthCard from '../components/ops/SystemHealthCard'
  import QueueLatencyCard from '../components/ops/QueueLatencyCard'
  import type { OpsStatsResponse } from '../api/types'

  export default function OpsMonitorV2() {
    const queryClient = useQueryClient()
    const activeProfile = useProfileStore((s) => s.activeProfile)
    const navigate = useNavigate()

    const [pollInterval, setPollInterval] = useState(() => {
      try {
        return Number(localStorage.getItem('ops_poll_interval')) || 10000
      } catch {
        return 10000
      }
    })
    const [timeWindow, setTimeWindow] = useState(() => {
      try {
        return localStorage.getItem('ops_time_window') || '1h'
      } catch {
        return '1h'
      }
    })
    const [muted, setMuted] = useState(() => {
      try {
        return localStorage.getItem('ops_muted') === 'true'
      } catch {
        return false
      }
    })

    const pollingEnabled = isEnabled('ff_ops_monitor_polling')

    const { data, error, isFetching, refetch } = useQuery({
      queryKey: queryKeys.opsMonitor(activeProfile ?? '', timeWindow),
      queryFn: async () => {
        const res = await apiClient<OpsStatsResponse>(
          `/api/stats/ops?profile=${encodeURIComponent(activeProfile ?? '')}&window=${timeWindow}`,
        )
        return res.data
      },
      enabled: !!activeProfile,
      refetchInterval: pollingEnabled ? pollInterval : false,
      refetchIntervalInBackground: false,
    })

    useOnActiveUserChanged(() => {
      queryClient.invalidateQueries({ queryKey: ['ops_monitor'] })
    })

    const loading = isFetching && !data
    const errorMsg = error ? String(error instanceof Error ? error.message : error) : ''

    const updateTimeWindow = (v: string) => {
      setTimeWindow(v)
      try { localStorage.setItem('ops_time_window', v) } catch { /* ignore */ }
    }
    const updatePollInterval = (v: number) => {
      setPollInterval(v)
      try { localStorage.setItem('ops_poll_interval', String(v)) } catch { /* ignore */ }
    }
    const updateMuted = (v: boolean) => {
      setMuted(v)
      try { localStorage.setItem('ops_muted', String(v)) } catch { /* ignore */ }
    }

    if (loading) {
      return (
        <div className="p-6 flex items-center justify-center h-64 bg-surface-base">
          <RefreshCw size={20} className="animate-spin text-text-muted" />
          <span className="ml-2 text-text-secondary text-sm">加载监控数据...</span>
        </div>
      )
    }

    return (
      <div className="p-6 space-y-4 bg-surface-base min-h-screen">
        {/* 告警条 */}
        {isEnabled('ff_ops_monitor_alert_bar') && data && !data.system_ok && (
          <div
            onClick={() => navigate('/preflight')}
            className="bg-error text-white px-4 py-2.5 rounded-button flex items-center justify-between cursor-pointer hover:bg-accent-hover transition-colors"
          >
            <div className="flex items-center gap-2">
              <AlertTriangle size={16} />
              <span className="text-sm font-medium">系统健康异常，点击查看详情</span>
            </div>
            <ChevronRight size={16} />
          </div>
        )}

        {/* Topbar */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Activity size={22} className="text-accent" />
            <div>
              <h2 className="text-xl font-bold text-text-primary">运维监控</h2>
              <p className="text-xs text-text-muted">{activeProfile ? `@${activeProfile}` : '加载中...'}</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <OpsSettingsPopover
              timeWindow={timeWindow}
              onTimeWindowChange={updateTimeWindow}
              pollInterval={pollInterval}
              onPollIntervalChange={updatePollInterval}
              muted={muted}
              onMutedChange={updateMuted}
              data={data}
            />
            <button
              onClick={() => refetch()}
              className="p-2 rounded-button hover:bg-surface-hover transition-colors text-text-secondary"
              title="手动刷新"
            >
              <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            </button>
            <button
              onClick={() => navigate('/today')}
              className="flex items-center gap-1.5 bg-accent hover:bg-accent-hover text-white px-4 py-2 rounded-button text-sm font-semibold transition-colors"
            >
              <PlayCircle size={16} />
              进入今日执行
            </button>
          </div>
        </div>

        <ErrorBanner
          message={errorMsg}
          mb="mb-0"
          size="base"
          trailing={errorMsg ? <button onClick={() => refetch()} className="text-sm underline">重试</button> : undefined}
        />

        {/* Hero */}
        {!muted && <OpsHero data={data} timeWindow={timeWindow} />}

        {/* 三卡 */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {!muted && <FailureHotspotsCard hotspots={data?.failure_hotspots ?? []} timeWindow={timeWindow} />}
          <SystemHealthCard systemOk={data?.system_ok !== false} checks={data?.health_checks ?? []} />
          {!muted && <QueueLatencyCard data={data} />}
        </div>
      </div>
    )
  }
  ```

- [ ] **Step 3.13: 在 OpsMonitor.tsx 顶部加 flag dispatch**

  打开 `web/frontend/src/pages/OpsMonitor.tsx`，在文件顶部 import 区追加：

  ```typescript
  import OpsMonitorV2 from './OpsMonitorV2'
  ```

  （注意：`isEnabled` 应已存在；如不存在，从 `../utils/featureFlags` 引入。）

  在 `export default function OpsMonitor() {` 函数体**第一行**（在任何 hook 调用之前）插入：

  ```typescript
    if (isEnabled('ff_redesign_ops')) return <OpsMonitorV2 />
  ```

  hooks 数量在生命周期内稳定（flag 来自 URL/localStorage，刷新页面才生效），React 不会报错；如 ESLint 抱怨加注释 disable 该行。

- [ ] **Step 3.14: 跑 build 确认通过**

  Run: `cd web/frontend && npm run build`
  Expected: 成功。

- [ ] **Step 3.15: 手动验证（dev server）**

  Run: `python scripts/start_web.py --dev --user <username>`
  浏览器 `http://localhost:5173/?ff_redesign_ops=on&ff_redesign_sidebar=on`：
  - 看到米白底 + 暖色 Sidebar + Hero + 三卡布局
  - 点设置按钮：弹出 popover 含时间窗口/轮询/静音/CSV
  - 点 popover 外部：popover 关闭
  - Esc 键：popover 关闭
  - 不带 flag 时：旧版蓝白 UI 不变（regression check）

- [ ] **Step 3.16: 提交 Ops 子组件**

  ```bash
  git add web/frontend/src/components/ops/ \
          web/frontend/src/pages/OpsMonitorV2.tsx \
          web/frontend/src/pages/OpsMonitor.tsx
  git commit -m "feat(web/ui): OpsMonitorV2 with Hero + 3 cards + settings popover

  - OpsHero (status badge + 3 stats + CTA)
  - FailureHotspotsCard / SystemHealthCard / QueueLatencyCard
  - OpsSettingsPopover collapses 5 controls into one popover
  - localStorage persists timeWindow / pollInterval / muted

  Guarded by ff_redesign_ops (default off). Spec §3."
  ```

---

## Task 4: TodayTasks V2（Spec §4，Step 4）

实现 4 态 Hero、useRunningElapsed 计时 hook、TodayTasksV2 页面。

**Files:**
- Create: `web/frontend/src/utils/todayHeroState.ts`
- Create: `web/frontend/src/utils/todayHeroState.test.ts`
- Create: `web/frontend/src/hooks/useRunningElapsed.ts`
- Create: `web/frontend/src/components/today/TodayHero.tsx`
- Create: `web/frontend/src/components/today/TodayHeroIdle.tsx`
- Create: `web/frontend/src/components/today/TodayHeroRunning.tsx`
- Create: `web/frontend/src/components/today/TodayHeroDone.tsx`
- Create: `web/frontend/src/components/today/TodayHeroEmpty.tsx`
- Create: `web/frontend/src/pages/TodayTasksV2.tsx`
- Modify: `web/frontend/src/pages/TodayTasks.tsx`

### 4A. 状态判定（纯函数 + 测试）

- [ ] **Step 4.1: 写状态判定测试**

  Create `web/frontend/src/utils/todayHeroState.test.ts`：

  ```typescript
  /**
   * todayHeroState.test.ts — Today Hero 四态判定纯函数测试。
   */
  import { describe, expect, it } from 'vitest'
  import { pickTodayHeroState } from './todayHeroState'

  describe('pickTodayHeroState', () => {
    it('running 优先级最高', () => {
      expect(pickTodayHeroState({ isTaskRunning: true, isTerminal: false, itemsCount: 5 })).toBe('running')
      expect(pickTodayHeroState({ isTaskRunning: true, isTerminal: true, itemsCount: 0 })).toBe('running')
    })

    it('terminal 第二优先级', () => {
      expect(pickTodayHeroState({ isTaskRunning: false, isTerminal: true, itemsCount: 5 })).toBe('done')
      expect(pickTodayHeroState({ isTaskRunning: false, isTerminal: true, itemsCount: 0 })).toBe('done')
    })

    it('itemsCount 为 0 走 empty', () => {
      expect(pickTodayHeroState({ isTaskRunning: false, isTerminal: false, itemsCount: 0 })).toBe('empty')
    })

    it('默认走 idle', () => {
      expect(pickTodayHeroState({ isTaskRunning: false, isTerminal: false, itemsCount: 5 })).toBe('idle')
    })
  })
  ```

- [ ] **Step 4.2: 跑测试确认失败**

  Run: `cd web/frontend && npx vitest run src/utils/todayHeroState.test.ts`
  Expected: FAIL，找不到模块。

- [ ] **Step 4.3: 实现 pickTodayHeroState**

  Create `web/frontend/src/utils/todayHeroState.ts`：

  ```typescript
  /**
   * utils/todayHeroState.ts — Today Hero 状态判定纯函数。
   *
   * 判定优先级（Spec §4.2）：
   *   isTaskRunning → isTerminal → itemsCount === 0 → 默认 idle
   */
  export type TodayHeroState = 'idle' | 'running' | 'done' | 'empty'

  export interface TodayHeroStateInput {
    isTaskRunning: boolean
    isTerminal: boolean
    itemsCount: number
  }

  export function pickTodayHeroState(input: TodayHeroStateInput): TodayHeroState {
    if (input.isTaskRunning) return 'running'
    if (input.isTerminal) return 'done'
    if (input.itemsCount === 0) return 'empty'
    return 'idle'
  }
  ```

- [ ] **Step 4.4: 跑测试确认通过 + 提交**

  ```bash
  cd web/frontend && npx vitest run src/utils/todayHeroState.test.ts
  ```
  Expected: 4 PASS。

  ```bash
  git add web/frontend/src/utils/todayHeroState.ts web/frontend/src/utils/todayHeroState.test.ts
  git commit -m "feat(web/ui): add pickTodayHeroState pure function

  Decides which Hero variant to render (idle/running/done/empty)
  based on task lifecycle + items count. Spec §4.2."
  ```

### 4B. useRunningElapsed hook

- [ ] **Step 4.5: 创建 useRunningElapsed.ts**

  Create `web/frontend/src/hooks/useRunningElapsed.ts`：

  ```typescript
  /**
   * hooks/useRunningElapsed.ts — running 状态下的"已耗时（秒）"，每秒 tick。
   * 纯渲染装饰；不入 useTodayController。Spec §6。
   */
  import { useEffect, useState } from 'react'

  export function useRunningElapsed(isRunning: boolean): number {
    const [start, setStart] = useState<number | null>(null)
    const [now, setNow] = useState(() => Date.now())

    useEffect(() => {
      if (isRunning && start == null) {
        setStart(Date.now())
        setNow(Date.now())
      } else if (!isRunning && start != null) {
        setStart(null)
      }
    }, [isRunning, start])

    useEffect(() => {
      if (!isRunning) return
      const id = setInterval(() => setNow(Date.now()), 1000)
      return () => clearInterval(id)
    }, [isRunning])

    return start ? Math.floor((now - start) / 1000) : 0
  }

  export function formatElapsed(sec: number): string {
    if (sec < 60) return `${sec}s`
    const m = Math.floor(sec / 60)
    const s = sec % 60
    return `${m}m ${s}s`
  }
  ```

### 4C. 4 个 Hero 变体组件

- [ ] **Step 4.6: 创建 TodayHeroIdle.tsx**

  Create `web/frontend/src/components/today/TodayHeroIdle.tsx`：

  ```typescript
  /**
   * components/today/TodayHeroIdle.tsx — Spec §4.2 ① Idle 状态。
   */
  import { PlayCircle, Filter } from 'lucide-react'

  export default function TodayHeroIdle({
    totalCount,
    executableCount,
    doneCount,
    showAll,
    onStart,
    onToggleShowAll,
    disabled,
  }: {
    totalCount: number
    executableCount: number
    doneCount: number
    showAll: boolean
    onStart: () => void
    onToggleShowAll: () => void
    disabled?: boolean
  }) {
    return (
      <div className="rounded-card border border-border-hero shadow-hero p-6 bg-gradient-to-br from-surface-card to-surface-highlight">
        <div className="text-xs text-text-muted mb-1">今日待处理 · 价值优先</div>
        <div className="text-3xl font-bold text-text-primary mb-2">{totalCount} 个单词</div>
        <div className="flex gap-3 text-sm text-text-secondary mb-4">
          <span><b className="text-text-primary">{executableCount}</b> 可执行</span>
          <span className="text-text-muted">·</span>
          <span><b className="text-text-primary">{doneCount}</b> 已完成</span>
        </div>
        <div className="flex gap-2">
          <button
            onClick={onStart}
            disabled={disabled || executableCount === 0}
            className="flex items-center gap-1.5 bg-accent hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed text-white px-5 py-2.5 rounded-button text-sm font-semibold transition-colors"
          >
            <PlayCircle size={16} />
            全部处理
          </button>
          <button
            onClick={onToggleShowAll}
            className="flex items-center gap-1.5 bg-accent-soft hover:bg-accent hover:text-white text-accent-hover px-4 py-2.5 rounded-button text-sm font-medium transition-colors"
          >
            <Filter size={14} />
            {showAll ? `仅可执行 (${executableCount})` : `查看全部 (${totalCount})`}
          </button>
        </div>
      </div>
    )
  }
  ```

- [ ] **Step 4.7: 创建 TodayHeroRunning.tsx**

  Create `web/frontend/src/components/today/TodayHeroRunning.tsx`：

  ```typescript
  /**
   * components/today/TodayHeroRunning.tsx — Spec §4.2 ② Running 状态。
   */
  import { Square, Clock, Zap } from 'lucide-react'
  import { useRunningElapsed, formatElapsed } from '../../hooks/useRunningElapsed'

  export default function TodayHeroRunning({
    currentWord,
    phase,
    doneCount,
    runningCount,
    errorCount,
    pendingCount,
    totalCount,
    onCancel,
    disabled,
  }: {
    currentWord: string | null
    phase: string | null
    doneCount: number
    runningCount: number
    errorCount: number
    pendingCount: number
    totalCount: number
    onCancel: () => void
    disabled?: boolean
  }) {
    const elapsed = useRunningElapsed(true)
    const finished = doneCount + errorCount
    const progressPct = totalCount > 0 ? Math.round((finished / totalCount) * 100) : 0

    return (
      <div className="rounded-card border border-border-hero shadow-hero p-6 bg-gradient-to-br from-surface-card to-surface-highlight">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-text-muted">正在处理 ({finished}/{totalCount})</span>
          <span className="text-xs text-text-muted flex items-center gap-1">
            <Clock size={11} />
            已耗时 {formatElapsed(elapsed)}
          </span>
        </div>
        <div className="text-2xl font-bold text-text-primary mb-2">{currentWord || '准备中...'}</div>
        {phase && (
          <div className="flex items-center gap-1.5 text-sm text-accent mb-3">
            <Zap size={12} />
            {phase}
          </div>
        )}
        <div className="bg-border-default h-1.5 rounded-pill overflow-hidden mb-3">
          <div className="bg-accent h-full transition-all" style={{ width: `${progressPct}%` }} />
        </div>
        <div className="flex items-center justify-between">
          <div className="flex gap-4 text-xs">
            <Stat label="完成" value={doneCount} />
            <Stat label="运行" value={runningCount} color="text-accent" />
            <Stat label="错误" value={errorCount} color="text-error" />
            <Stat label="待" value={pendingCount} />
          </div>
          <button
            onClick={onCancel}
            disabled={disabled}
            className="flex items-center gap-1.5 bg-error hover:opacity-90 disabled:opacity-50 text-white px-4 py-2 rounded-button text-sm font-semibold transition-opacity"
          >
            <Square size={14} />
            停止处理
          </button>
        </div>
      </div>
    )
  }

  function Stat({ label, value, color }: { label: string; value: number; color?: string }) {
    return (
      <span>
        <b className={`text-sm font-bold ${color || 'text-text-primary'}`}>{value}</b>
        <span className="text-text-muted ml-1">{label}</span>
      </span>
    )
  }
  ```

- [ ] **Step 4.8: 创建 TodayHeroDone.tsx**

  Create `web/frontend/src/components/today/TodayHeroDone.tsx`：

  ```typescript
  /**
   * components/today/TodayHeroDone.tsx — Spec §4.2 ③ Done 状态（决策 Z：不变色）。
   */
  import { Check, RotateCw } from 'lucide-react'

  export default function TodayHeroDone({
    doneCount,
    errorCount,
    skippedCount,
    totalCount,
    onViewFailures,
    onRetryBatch,
  }: {
    doneCount: number
    errorCount: number
    skippedCount: number
    totalCount: number
    onViewFailures?: () => void
    onRetryBatch: () => void
  }) {
    const successRate = totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0
    return (
      <div className="rounded-card border border-border-hero shadow-hero p-6 bg-gradient-to-br from-surface-card to-surface-highlight">
        <div className="flex items-center gap-2 mb-2">
          <Check size={16} className="text-text-primary" />
          <span className="text-xs text-text-muted">处理完成</span>
        </div>
        <div className="text-2xl font-bold text-text-primary mb-2">
          {doneCount} 成功 · {errorCount} 失败 · {skippedCount} 跳过
        </div>
        <div className="text-sm text-text-secondary mb-4">
          <span><b className="text-text-primary">{successRate}%</b> 成功率</span>
        </div>
        <div className="flex gap-2">
          {errorCount > 0 && onViewFailures && (
            <button
              onClick={onViewFailures}
              className="flex items-center gap-1.5 bg-error hover:opacity-90 text-white px-4 py-2.5 rounded-button text-sm font-semibold transition-opacity"
            >
              查看失败 ({errorCount}) →
            </button>
          )}
          <button
            onClick={onRetryBatch}
            className="flex items-center gap-1.5 bg-accent-soft hover:bg-accent hover:text-white text-accent-hover px-4 py-2.5 rounded-button text-sm font-medium transition-colors"
          >
            <RotateCw size={14} />
            再来一批
          </button>
        </div>
      </div>
    )
  }
  ```

- [ ] **Step 4.9: 创建 TodayHeroEmpty.tsx**

  Create `web/frontend/src/components/today/TodayHeroEmpty.tsx`：

  ```typescript
  /**
   * components/today/TodayHeroEmpty.tsx — Spec §4.2 ④ Empty 状态。
   */
  import { useNavigate } from 'react-router-dom'

  export default function TodayHeroEmpty() {
    const navigate = useNavigate()
    return (
      <div className="rounded-card border-2 border-dashed border-border-default p-8 bg-surface-card text-center">
        <div className="text-4xl mb-2">🎉</div>
        <div className="text-base font-semibold text-text-primary mb-1">今日已清空</div>
        <div className="text-sm text-text-muted mb-4">没有待处理的单词了。</div>
        <div className="flex gap-2 justify-center">
          <button
            onClick={() => navigate('/future')}
            className="bg-accent-soft hover:bg-accent hover:text-white text-accent-hover px-4 py-2 rounded-button text-sm font-medium transition-colors"
          >
            看未来计划 →
          </button>
          <button
            onClick={() => navigate('/iteration')}
            className="bg-accent-soft hover:bg-accent hover:text-white text-accent-hover px-4 py-2 rounded-button text-sm font-medium transition-colors"
          >
            智能迭代 →
          </button>
        </div>
      </div>
    )
  }
  ```

- [ ] **Step 4.10: 创建 TodayHero 分发器**

  Create `web/frontend/src/components/today/TodayHero.tsx`：

  ```typescript
  /**
   * components/today/TodayHero.tsx — Today 顶部 Hero 4 态分发。Spec §4.2。
   */
  import { pickTodayHeroState } from '../../utils/todayHeroState'
  import TodayHeroIdle from './TodayHeroIdle'
  import TodayHeroRunning from './TodayHeroRunning'
  import TodayHeroDone from './TodayHeroDone'
  import TodayHeroEmpty from './TodayHeroEmpty'

  export interface TodayHeroProps {
    isTaskRunning: boolean
    isTerminal: boolean
    totalCount: number
    executableCount: number
    doneCount: number
    errorCount: number
    skippedCount: number
    runningCount: number
    pendingCount: number
    currentWord: string | null
    currentPhase: string | null
    showAll: boolean
    onStart: () => void
    onCancel: () => void
    onToggleShowAll: () => void
    onViewFailures?: () => void
    onRetryBatch: () => void
    disabled?: boolean
  }

  export default function TodayHero(props: TodayHeroProps) {
    const state = pickTodayHeroState({
      isTaskRunning: props.isTaskRunning,
      isTerminal: props.isTerminal,
      itemsCount: props.totalCount,
    })

    if (state === 'running') {
      return (
        <TodayHeroRunning
          currentWord={props.currentWord}
          phase={props.currentPhase}
          doneCount={props.doneCount}
          runningCount={props.runningCount}
          errorCount={props.errorCount}
          pendingCount={props.pendingCount}
          totalCount={props.totalCount}
          onCancel={props.onCancel}
          disabled={props.disabled}
        />
      )
    }
    if (state === 'done') {
      return (
        <TodayHeroDone
          doneCount={props.doneCount}
          errorCount={props.errorCount}
          skippedCount={props.skippedCount}
          totalCount={props.totalCount}
          onViewFailures={props.onViewFailures}
          onRetryBatch={props.onRetryBatch}
        />
      )
    }
    if (state === 'empty') return <TodayHeroEmpty />
    return (
      <TodayHeroIdle
        totalCount={props.totalCount}
        executableCount={props.executableCount}
        doneCount={props.doneCount}
        showAll={props.showAll}
        onStart={props.onStart}
        onToggleShowAll={props.onToggleShowAll}
        disabled={props.disabled}
      />
    )
  }
  ```

### 4D. TodayTasksV2 页面

- [ ] **Step 4.11: 创建 TodayTasksV2.tsx**

  Create `web/frontend/src/pages/TodayTasksV2.tsx`：

  ```typescript
  /**
   * pages/TodayTasksV2.tsx — Today 任务页重绘版本。Spec §4。
   *
   * 复用 useTodayController（数据 + 状态机 + 业务逻辑全部不动），
   * 只换渲染：Hero 4 态 + 紧凑表格 + 暖色 pill。
   */
  import { useMemo, useRef } from 'react'
  import { Filter, Eye, EyeOff, Info, RotateCw } from 'lucide-react'
  import { rowStatusLabel, rowPhaseLabel } from '../utils/rowProgress'
  import { useTodayController } from '../hooks/useTodayController'
  import ErrorBanner from '../components/ui/ErrorBanner'
  import LightConfirmBar from '../components/today/LightConfirmBar'
  import FailureGroupsPanel from '../components/today/FailureGroupsPanel'
  import BulkGuardModal from '../components/today/BulkGuardModal'
  import TodayHero from '../components/today/TodayHero'

  export default function TodayTasksV2() {
    const rowRefs = useRef<Map<string, HTMLTableRowElement>>(new Map())
    const c = useTodayController(rowRefs)

    // 找当前 running 词 + phase（rowStatusMap 的 key 是 lowercase，从 items 拿原始大小写）
    const runningItem = c.items.find(
      (it) => c.rowStatusMap[(it.voc_spelling || '').toLowerCase()]?.status === 'running',
    )
    const currentWord = runningItem?.voc_spelling ?? null
    const currentPhase = runningItem
      ? c.rowStatusMap[(runningItem.voc_spelling || '').toLowerCase()]?.phase ?? null
      : null

    // statusCounts 只有 done/error/skipped；running/pending 本地补
    const runningCount = useMemo(
      () => Object.values(c.rowStatusMap).filter((s) => s?.status === 'running').length,
      [c.rowStatusMap],
    )
    const pendingCount = Math.max(
      0,
      c.items.length - c.statusCounts.done - c.statusCounts.error - c.statusCounts.skipped - runningCount,
    )

    return (
      <div className="p-6 bg-surface-base min-h-screen">
        <div className="flex items-center justify-between mb-6">
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-bold text-text-primary">今日任务</h2>
              <button
                onClick={c.refresh}
                disabled={c.refreshing || c.processing}
                className="p-1.5 rounded-pill hover:bg-surface-hover text-text-muted hover:text-text-primary transition-all active:scale-90 disabled:opacity-30"
                title="强制从墨墨 API 刷新列表"
              >
                <RotateCw size={16} className={c.refreshing ? 'animate-spin' : ''} />
              </button>
            </div>
            <p className="text-text-secondary text-sm flex items-center gap-2">
              {c.data ? `${c.data.count} 个单词待处理` : '加载中...'}
              {c.data?.ts && !c.refreshing && (
                <span className="text-xs text-text-muted">
                  (数据更新于 {new Date(c.data.ts * 1000).toLocaleTimeString()})
                </span>
              )}
            </p>
          </div>
        </div>

        {/* Hero */}
        <TodayHero
          isTaskRunning={c.isTaskRunning}
          isTerminal={c.isTerminal}
          totalCount={c.items.length}
          executableCount={c.executableItems.length}
          doneCount={c.statusCounts.done}
          errorCount={c.statusCounts.error}
          skippedCount={c.statusCounts.skipped}
          runningCount={runningCount}
          pendingCount={pendingCount}
          currentWord={currentWord}
          currentPhase={currentPhase}
          showAll={c.showAll}
          onStart={c.handleClick}
          onCancel={() => c.handleCancel()}
          onToggleShowAll={() => c.setShowAll((v) => !v)}
          onViewFailures={c.flags.failureGroups ? () => c.setShowFailureMode(true) : undefined}
          onRetryBatch={() => c.refresh()}
          disabled={c.processing || c.refreshing || c.confirmingProcess}
        />

        {/* V1-T2: 轻确认条 */}
        {c.confirmingProcess && (
          <div className="mt-4">
            <LightConfirmBar
              count={c.executableItems.length}
              onConfirm={() => c.handleProcess()}
              onCancel={() => c.setConfirmingProcess(false)}
              loading={c.processing}
            />
          </div>
        )}

        {/* V1-T7: 大批量二次确认 */}
        {c.confirmingBulk && (
          <BulkGuardModal
            count={c.executableItems.length}
            onConfirm={() => {
              c.setConfirmingBulk(false)
              c.handleProcess()
            }}
            onCancel={() => c.setConfirmingBulk(false)}
          />
        )}

        {c.showFailureMode && c.flags.failureGroups ? (
          <div className="mt-4">
            <FailureGroupsPanel
              groups={c.failureGroups}
              rowStatusMap={c.rowStatusMap}
              onBack={() => c.setShowFailureMode(false)}
              onRetryGroup={c.flags.groupRetry ? (g) => c.handleProcess(g.items.map((it) => it.voc_id)) : undefined}
            />
          </div>
        ) : (
          <>
            {/* 筛选条 */}
            {c.flags.defaultView && c.data && c.items.length > 0 && (
              <>
                <div className="mt-4 mb-2 flex items-center gap-3 text-sm">
                  <button
                    onClick={() => c.setShowAll((v) => !v)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-button border border-border-default hover:bg-surface-hover transition-colors text-text-secondary"
                  >
                    <Filter size={14} />
                    {c.showAll ? `查看全部 (${c.sortedItems.length})` : `仅可执行 (${c.executableItems.length})`}
                  </button>
                  {!c.showAll && c.hiddenCount > 0 && (
                    <span className="text-xs text-text-muted">已隐藏 {c.hiddenCount} 条已完成/跳过项</span>
                  )}
                  <span className="text-xs text-text-muted">价值优先 · 时间压力次级</span>
                  {c.flags.followRunning && c.isTaskRunning && (
                    <button
                      onClick={() => c.setFollowPaused((v) => !v)}
                      className="flex items-center gap-1 px-2 py-1 rounded-pill text-xs border border-border-default hover:bg-surface-hover transition-colors text-text-secondary ml-auto"
                    >
                      {c.followPaused ? <><Eye size={12} /> 恢复跟随</> : <><EyeOff size={12} /> 暂停跟随</>}
                    </button>
                  )}
                </div>
                {c.isTaskRunning && (
                  <div className="mb-2 flex items-center gap-1.5 text-xs text-accent">
                    <Info size={12} />
                    筛选仅影响显示，不影响正在执行的任务
                  </div>
                )}
              </>
            )}

            <ErrorBanner message={c.errorMsg} size="base" />

            {c.data && c.displayItems.length > 0 && (
              <div className="bg-surface-card rounded-card shadow-card overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-surface-hover">
                    <tr>
                      <th className="text-left px-4 py-2 font-medium text-text-secondary">#</th>
                      <th className="text-left px-4 py-2 font-medium text-text-secondary">单词</th>
                      <th className="text-left px-4 py-2 font-medium text-text-secondary">进度</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.displayItems.map((item, i) => {
                      const state = c.rowStatusMap[item.voc_spelling.toLowerCase()]
                      const status = state?.status || 'pending'
                      const phase = state?.phase
                      const isRunning = status === 'running'
                      const pillClass = {
                        pending: 'bg-surface-hover text-text-secondary',
                        running: 'bg-accent-soft text-accent-hover border border-accent',
                        done: 'bg-surface-hover text-text-secondary',
                        error: 'bg-error-soft text-error',
                        warning: 'bg-accent-soft text-accent-hover',
                      }[status as 'pending' | 'running' | 'done' | 'error' | 'warning']
                      return (
                        <tr
                          key={item.voc_id}
                          className={`border-t border-border-soft hover:bg-surface-hover ${isRunning ? 'bg-surface-highlight' : ''}`}
                          ref={(el) => {
                            const k = (item.voc_spelling || '').toLowerCase()
                            if (el) rowRefs.current.set(k, el)
                            else rowRefs.current.delete(k)
                          }}
                        >
                          <td className="px-4 py-2 text-text-muted">{i + 1}</td>
                          <td className="px-4 py-2 font-medium text-text-primary">{item.voc_spelling}</td>
                          <td className="px-4 py-2">
                            <div className="flex flex-col gap-1">
                              <div className={`inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded-pill w-fit font-medium ${pillClass}`}>
                                {isRunning && <RotateCw size={10} className="animate-spin" />}
                                {rowStatusLabel(status as 'pending' | 'running' | 'done' | 'error' | 'warning')}
                              </div>
                              {phase && phase !== status && (
                                <span className={`text-[10px] font-normal ml-0.5 ${
                                  status === 'error' ? 'text-error' :
                                  status === 'warning' ? 'text-accent' :
                                  status === 'done' ? 'text-text-muted' : 'text-accent'
                                }`}>
                                  {rowPhaseLabel(phase)}
                                </span>
                              )}
                              {(status === 'error' || status === 'warning') && state.reason && (
                                <span className={`text-[10px] font-normal ml-0.5 max-w-[200px] truncate ${status === 'error' ? 'text-error' : 'text-accent'}`}>
                                  {state.reason}
                                </span>
                              )}
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {c.data && c.items.length > 0 && c.displayItems.length === 0 && (
              <div className="text-center py-12 text-text-muted">
                所有项均已完成或跳过 · 点"查看全部"可显示完整列表
              </div>
            )}
          </>
        )}
      </div>
    )
  }
  ```

- [ ] **Step 4.12: 在 TodayTasks.tsx 顶部加 flag dispatch**

  打开 `web/frontend/src/pages/TodayTasks.tsx`，在 import 区追加：

  ```typescript
  import { isEnabled } from '../utils/featureFlags'
  import TodayTasksV2 from './TodayTasksV2'
  ```

  在 `export default function TodayTasks() {` 函数体第一行（rowRefs/controller 之前）插入：

  ```typescript
    if (isEnabled('ff_redesign_today')) return <TodayTasksV2 />
  ```

- [ ] **Step 4.13: 跑 build + 测试**

  Run: `cd web/frontend && npm run build && npx vitest run`
  Expected: build 成功，所有测试 PASS。

- [ ] **Step 4.14: 手动验证 4 个 Hero 状态**

  Run: `python scripts/start_web.py --dev --user <username>`
  浏览器 `http://localhost:5173/today?ff_redesign_today=on&ff_redesign_sidebar=on`：
  - 有待处理时：看到 **Idle Hero**，大字数字 + 全部处理按钮
  - 点"全部处理"开始执行：看到 **Running Hero**，当前词 + 阶段 + 进度条 + 已耗时计时
  - 执行完后：看到 **Done Hero**，✓ + 成功率（**无绿色**，靠图标传达）
  - 当 `data.count === 0` 时：看到 **Empty Hero**，🎉 + 两个引导按钮（可用 mock 数据或等到自然空）

- [ ] **Step 4.15: 提交 Today V2**

  ```bash
  git add web/frontend/src/utils/todayHeroState.ts \
          web/frontend/src/utils/todayHeroState.test.ts \
          web/frontend/src/hooks/useRunningElapsed.ts \
          web/frontend/src/components/today/TodayHero.tsx \
          web/frontend/src/components/today/TodayHeroIdle.tsx \
          web/frontend/src/components/today/TodayHeroRunning.tsx \
          web/frontend/src/components/today/TodayHeroDone.tsx \
          web/frontend/src/components/today/TodayHeroEmpty.tsx \
          web/frontend/src/pages/TodayTasksV2.tsx \
          web/frontend/src/pages/TodayTasks.tsx
  git commit -m "feat(web/ui): TodayTasksV2 with 4-state Progress Hero

  - pickTodayHeroState decides idle/running/done/empty
  - 4 Hero variants share idle's warm gradient (decision Z: no color shift on done)
  - useRunningElapsed local timer for 'elapsed' display
  - useTodayController interface unchanged

  Guarded by ff_redesign_today (default off). Spec §4."
  ```

---

## Task 5: Drill-down 上下文传递（Spec §3.5 + §4.4，Step 5）

OpsMonitor 已经在 hotspot 点击时传 `?error_type=&window=`；Today 页解析并显示 `DrillDownNotice`，点 ✕ 清除参数。本期**只显示通知**，不实际过滤 items 列表（待处理词列表与历史错误是不同概念）。

**Files:**
- Create: `web/frontend/src/utils/drillDown.ts`
- Create: `web/frontend/src/utils/drillDown.test.ts`
- Create: `web/frontend/src/components/today/DrillDownNotice.tsx`
- Modify: `web/frontend/src/pages/TodayTasksV2.tsx`

### 5A. URL 参数解析（纯函数）

- [ ] **Step 5.1: 写解析测试**

  Create `web/frontend/src/utils/drillDown.test.ts`：

  ```typescript
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
  ```

- [ ] **Step 5.2: 跑测试确认失败**

  Run: `cd web/frontend && npx vitest run src/utils/drillDown.test.ts`
  Expected: FAIL，模块不存在。

- [ ] **Step 5.3: 实现 drillDown 工具**

  Create `web/frontend/src/utils/drillDown.ts`：

  ```typescript
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
  ```

- [ ] **Step 5.4: 跑测试确认通过**

  Run: `cd web/frontend && npx vitest run src/utils/drillDown.test.ts`
  Expected: 7 PASS。

### 5B. DrillDownNotice 组件

- [ ] **Step 5.5: 创建 DrillDownNotice.tsx**

  Create `web/frontend/src/components/today/DrillDownNotice.tsx`：

  ```typescript
  /**
   * components/today/DrillDownNotice.tsx — Spec §4.4 OpsMonitor drill-down 进入提示条。
   */
  import { Filter, X } from 'lucide-react'

  export default function DrillDownNotice({
    label,
    onClear,
  }: {
    label: string
    onClear: () => void
  }) {
    return (
      <div className="flex items-center gap-2 bg-accent-soft text-accent-hover px-3 py-2 rounded-button text-sm mt-3 mb-1">
        <Filter size={14} />
        <span>已应用筛选：<b>{label}</b></span>
        <button
          onClick={onClear}
          className="ml-auto text-accent-hover hover:text-accent-hover/80 p-1 rounded-pill hover:bg-accent-soft"
          title="清除筛选"
        >
          <X size={14} />
        </button>
      </div>
    )
  }
  ```

### 5C. 在 TodayTasksV2 中接入

- [ ] **Step 5.6: 在 TodayTasksV2 中读 URL 参数 + 显示 Notice**

  打开 `web/frontend/src/pages/TodayTasksV2.tsx`，在 import 区追加：

  ```typescript
  import { useSearchParams } from 'react-router-dom'
  import { parseDrillDownParams, isDrillDownActive, drillDownLabel } from '../utils/drillDown'
  import { isEnabled } from '../utils/featureFlags'
  import DrillDownNotice from '../components/today/DrillDownNotice'
  ```

  在 `const c = useTodayController(rowRefs)` 后追加：

  ```typescript
    const [searchParams, setSearchParams] = useSearchParams()
    const drill = parseDrillDownParams(searchParams)
    const drillActive = isEnabled('ff_drilldown_v2') && isDrillDownActive(drill)

    const clearDrillDown = () => {
      const next = new URLSearchParams(searchParams)
      next.delete('error_type')
      next.delete('window')
      setSearchParams(next, { replace: true })
    }
  ```

  在 `<TodayHero ... />` 后、`{c.confirmingProcess && ...}` 前，插入：

  ```typescript
        {drillActive && (
          <DrillDownNotice label={drillDownLabel(drill)} onClear={clearDrillDown} />
        )}
  ```

- [ ] **Step 5.7: 跑 build + 测试**

  Run: `cd web/frontend && npm run build && npx vitest run`
  Expected: 都 PASS。

- [ ] **Step 5.8: 端到端手动验证**

  Run: `python scripts/start_web.py --dev --user <username>`
  浏览器流程：
  1. 打开 `http://localhost:5173/?ff_redesign_ops=on&ff_redesign_today=on&ff_redesign_sidebar=on&ff_drilldown_v2=on`
  2. 在 OpsMonitor 失败热点卡片中点击任意一项
  3. 跳转到 Today，URL 应该是 `?error_type=xxx&window=1h`
  4. Today 页应该在 Hero 下方显示 **DrillDownNotice**：`已应用筛选：xxx 错误 · 1h ✕`
  5. 点 ✕：URL 参数被清除，notice 消失
  6. 不带 `ff_drilldown_v2=on` 时：即便有 URL 参数也不显示 notice（向后兼容旧逻辑）

- [ ] **Step 5.9: 提交 drill-down**

  ```bash
  git add web/frontend/src/utils/drillDown.ts \
          web/frontend/src/utils/drillDown.test.ts \
          web/frontend/src/components/today/DrillDownNotice.tsx \
          web/frontend/src/pages/TodayTasksV2.tsx
  git commit -m "feat(web/ui): drill-down notice from OpsMonitor → Today

  - parseDrillDownParams reads ?error_type & ?window
  - DrillDownNotice shows applied filter with ✕ to clear
  - Notice shows below Hero, gated by ff_drilldown_v2

  Note: this only displays the context tag; actual list filtering
  is not implemented in v1 (待处理词列表 vs error history are
  different concepts). Spec §3.5 / §4.4."
  ```

---

## Task 6: 最终验证

把所有改动一起跑一遍，确认无回归。

- [ ] **Step 6.1: 全部测试**

  Run: `cd web/frontend && npx vitest run`
  Expected: 所有 unit tests PASS。

- [ ] **Step 6.2: build**

  Run: `cd web/frontend && npm run build`
  Expected: 成功。

- [ ] **Step 6.3: lint**

  Run: `cd web/frontend && npm run lint`
  Expected: 0 warnings（项目设了 `--max-warnings=0`）。

- [ ] **Step 6.4: 默认行为回归验证（所有 flag off）**

  Run: `python scripts/start_web.py --dev --user <username>`
  浏览器不加任何 flag query 参数：
  - Sidebar 仍是 **旧版深色 gray-900**
  - OpsMonitor 仍是 **旧版 2x2 卡片网格**
  - TodayTasks 仍是 **旧版表格 + 蓝色 CTA**
  - 没有任何 visual regression

- [ ] **Step 6.5: 新 UI 全开验证**

  浏览器 `?ff_redesign_sidebar=on&ff_redesign_ops=on&ff_redesign_today=on&ff_drilldown_v2=on`：
  - Sidebar 米色暖调
  - OpsMonitor Hero + 三卡 + 设置 popover
  - TodayTasks 4 态 Hero（自然观察 idle，触发 running，等到 done）
  - OpsMonitor 点失败热点 → Today 显示 drill-down notice
  - 设置 popover：选择持久化到 localStorage（刷新仍记忆）
  - 静音模式：Hero 和"任务态势"/"失败热点"/"队列与延迟"3 卡都消失，只剩"系统健康"

- [ ] **Step 6.6: 异常路径**

  - 后端关掉：errorBanner 显示
  - 切换 profile：所有 V2 页面 query 重新拉取，状态正确
  - 一键 kill switch：在浏览器 console 执行 `localStorage.setItem('ff_off', 'v2')` 再刷新，所有 V2 + V3 flag 全部 off，回到老 UI

- [ ] **Step 6.7: （可选）合到 main 的 PR**

  如果决定合并：

  ```bash
  git push -u origin <current-branch>
  gh pr create --title "feat(web/ui): warm Notion redesign for OpsMonitor + TodayTasks + Sidebar" \
    --body "$(cat <<'EOF'
  ## Summary
  - 4 new feature flags (ff_redesign_sidebar / ff_redesign_ops / ff_redesign_today / ff_drilldown_v2), all default off
  - Tailwind v4 @theme tokens for warm color palette
  - SidebarV2 / OpsMonitorV2 / TodayTasksV2 as parallel implementations behind flags
  - Drill-down context notice from OpsMonitor failure hotspots

  ## Test plan
  - [ ] All flags off → no regression to existing UI
  - [ ] Each flag on independently → V2 component renders correctly
  - [ ] OpsMonitor settings popover: outside-click + Escape close
  - [ ] Today Hero: 4 states (idle/running/done/empty) all render
  - [ ] Drill-down: OpsMonitor → Today with ?error_type → notice appears, ✕ clears
  - [ ] localStorage persists time window / poll interval / muted
  - [ ] Kill switch ff_off=v2 disables all flags
  EOF
  )"
  ```

---

## 附：实施提示

### 文件提交粒度建议

| 任务 | 建议 commit 数 |
| --- | --- |
| Task 1 (Tokens) | 1 |
| Task 2 (Sidebar) | 2 (flag 注册 + 实现) |
| Task 3 (OpsMonitor) | 2-3 (usePopover + 子组件 + 页面) |
| Task 4 (TodayTasks) | 2 (状态函数 + V2 页面) |
| Task 5 (Drill-down) | 1 |
| Task 6 (最终验证) | 0（不提交，验证用） |

### 调试小贴士

- 浏览器 console：`window.__momoFlags()` 看当前所有 flag 状态
- 切换单个 flag：`localStorage.setItem('ff_redesign_today', 'on')` 然后 F5
- 单独跑某测试文件：`npx vitest run src/utils/<file>.test.ts`
- watch 模式：`npm run test:watch`
- 查 Hero 当前状态：在 TodayTasksV2 加临时 `console.log(pickTodayHeroState({...}))`

### 不动的护栏

实施过程中如果不小心动到这些文件，停下来 revert：
- `web/backend/**` 所有后端代码
- `web/frontend/src/hooks/useTodayController.ts`
- `web/frontend/src/api/`
- `web/frontend/src/stores/`
- `web/frontend/src/queries/`
- `web/frontend/src/components/tasks/TaskDrawer.tsx`
- 其他页面（Future / Iteration / Words / Sync / Preflight / Users / Gateway）

---

## 决策溯源

参见 spec [`docs/superpowers/specs/2026-05-11-web-ui-redesign-ops-and-today-design.md`](../specs/2026-05-11-web-ui-redesign-ops-and-today-design.md) 附录"决策溯源"表。
