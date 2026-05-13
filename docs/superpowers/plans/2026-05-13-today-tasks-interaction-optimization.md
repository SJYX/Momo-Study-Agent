# Today Tasks Interaction Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the "Hybrid Smart Dashboard" design for Today Tasks, featuring a ring chart hero, powerful filtering, inline status animations, inline error retries, and a floating bottom bar for batch operations.

**Architecture:** We will modify the existing `useTodayController` to support a new `filterView` state, batch mode `selectedIds`, and derived list computations based on the active view. The presentation layer (`TodayTasksV2.tsx`, `TodayHero.tsx`, etc.) will be refactored into modular components implementing the Unified Design Language (Notion-style). We will add a new `BottomBar` component for the batch mode.

**Tech Stack:** React, Tailwind CSS, Lucide Icons, React Query, Zustand.

---

### Task 1: Update Controller State (View Filters & Batch Mode)

We need to add state and derived data to support the new filtering logic and batch mode selection in `useTodayController`.

**Files:**
- Modify: `web/frontend/src/hooks/useTodayController.ts`

- [ ] **Step 1: Add state for filter view, batch mode and selected items**

```typescript
// Add these to the states section:
  const [filterView, setFilterView] = useState<'all' | 'pending' | 'error' | 'new' | 'review'>('all')
  const [isBatchMode, setIsBatchMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
```

- [ ] **Step 2: Update derived data for displayItems based on filterView**

```typescript
// Replace executableItems and displayItems derived logic:
  const filteredItems = useMemo(() => {
    switch (filterView) {
      case 'pending': return sortedItems.filter(it => {
        const s = rowStatusMap[(it.voc_spelling || '').toLowerCase()]
        return !s || s.phase !== 'skipped' && s.status !== 'done' && s.status !== 'error'
      })
      case 'error': return sortedItems.filter(it => 
        rowStatusMap[(it.voc_spelling || '').toLowerCase()]?.status === 'error'
      )
      case 'new': return sortedItems.filter(it => 
        typeof it.review_count === 'number' && it.review_count === 0
      )
      case 'review': return sortedItems.filter(it => 
        typeof it.review_count === 'number' && it.review_count > 0
      )
      case 'all':
      default: return sortedItems
    }
  }, [filterView, sortedItems, rowStatusMap])

  const displayItems = useMemo(() => {
    let list = [...filteredItems]
    if (taskStatus === 'running' || taskStatus === 'pending') {
      list.sort((a, b) => {
        const aStatus = rowStatusMap[(a.voc_spelling || '').toLowerCase()]?.status
        const bStatus = rowStatusMap[(b.voc_spelling || '').toLowerCase()]?.status
        if (aStatus === 'running' && bStatus !== 'running') return -1
        if (aStatus !== 'running' && bStatus === 'running') return 1
        return 0
      })
    }
    return list
  }, [filteredItems, taskStatus, rowStatusMap])
```

- [ ] **Step 3: Expose new states and actions**

```typescript
// Add to return object:
    filterView,
    isBatchMode,
    selectedIds,
    filteredItemsCount: filteredItems.length,
    setFilterView,
    setIsBatchMode,
    setSelectedIds,
```

- [ ] **Step 4: Commit**

```bash
git add web/frontend/src/hooks/useTodayController.ts
git commit -m "feat(today): add filter view and batch mode state to controller"
```

### Task 2: Implement Ring Chart and Enhanced Hero (Idle State)

Create a simple Ring Chart component and update `TodayHeroIdle` to use it along with the new filter bar.

**Files:**
- Create: `web/frontend/src/components/ui/RingChart.tsx`
- Modify: `web/frontend/src/components/today/TodayHeroIdle.tsx`
- Modify: `web/frontend/src/components/today/TodayHero.tsx`

- [ ] **Step 1: Create RingChart component**

```tsx
import React from 'react'

export function RingChart({ percentage, size = 60, strokeWidth = 6 }: { percentage: number, size?: number, strokeWidth?: number }) {
  const radius = (size - strokeWidth) / 2
  const circumference = radius * 2 * Math.PI
  const strokeDashoffset = circumference - (percentage / 100) * circumference

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg className="transform -rotate-90" width={size} height={size}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          strokeWidth={strokeWidth}
          fill="transparent"
          className="text-surface-hover"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          strokeWidth={strokeWidth}
          fill="transparent"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          className="text-accent transition-all duration-500 ease-in-out"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center text-xs font-semibold text-text-primary">
        {Math.round(percentage)}%
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Update TodayHeroIdle to include RingChart and smart button**

```tsx
import { RingChart } from '../ui/RingChart'

// Update props interface
export interface TodayHeroIdleProps {
  totalCount: number
  doneCount: number
  errorCount: number
  filteredCount: number
  filterView: string
  onStart: () => void
  disabled?: boolean
  onRetryFailures?: () => void
}

export default function TodayHeroIdle(props: TodayHeroIdleProps) {
  const percentage = props.totalCount > 0 ? (props.doneCount / props.totalCount) * 100 : 0
  const actionText = props.filterView === 'all' ? `处理剩余 (${props.filteredCount - props.doneCount})` : `处理选中视图 (${props.filteredCount})`

  return (
    <div className="bg-gradient-to-br from-surface-highlight to-surface-base rounded-card border border-border-hero shadow-hero p-5 mb-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <RingChart percentage={percentage} />
          <div>
            <h2 className="text-lg font-semibold text-text-primary">今日进度</h2>
            <p className="text-sm text-text-secondary mt-1">{props.doneCount} / {props.totalCount} 已完成</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {props.errorCount > 0 && props.onRetryFailures && (
            <button 
              onClick={props.onRetryFailures}
              disabled={props.disabled}
              className="bg-error-soft text-error px-4 py-2 rounded-button text-sm font-medium hover:bg-error/10 transition-colors"
            >
              ↻ 重试 {props.errorCount} 个失败
            </button>
          )}
          <button
            onClick={props.onStart}
            disabled={props.disabled || props.filteredCount === 0}
            className="bg-accent text-white px-4 py-2 rounded-button text-sm font-medium hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            🚀 {actionText}
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Update TodayHero props and routing**

```tsx
// In TodayHero.tsx, add to TodayHeroProps:
  filteredCount: number
  filterView: string
  onRetryFailures?: () => void

// Pass to TodayHeroIdle:
    <TodayHeroIdle
      totalCount={props.totalCount}
      doneCount={props.doneCount}
      errorCount={props.errorCount}
      filteredCount={props.filteredCount}
      filterView={props.filterView}
      onStart={props.onStart}
      disabled={props.disabled}
      onRetryFailures={props.onRetryFailures}
    />
```

- [ ] **Step 4: Commit**

```bash
git add web/frontend/src/components/ui/RingChart.tsx web/frontend/src/components/today/TodayHeroIdle.tsx web/frontend/src/components/today/TodayHero.tsx
git commit -m "feat(today): implement ring chart and smart hero buttons"
```

### Task 3: Implement Filter Bar & Connect to Controller

Implement the Filter Bar in `TodayTasksV2` to drive the `filterView` state.

**Files:**
- Modify: `web/frontend/src/pages/TodayTasksV2.tsx`

- [ ] **Step 1: Replace existing showAll filter UI with the new Filter Bar**

```tsx
// In TodayTasksV2.tsx, replace the `<div className="mt-4 mb-2 flex items-center gap-3 text-sm">` section with:

              <div className="mt-4 mb-3 flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                  {(['all', 'pending', 'error', 'new', 'review'] as const).map(view => {
                    const label = {
                      all: `全部 (${c.items.length})`,
                      pending: `待处理`,
                      error: `已失败`,
                      new: `新词`,
                      review: `复习词`
                    }[view]
                    return (
                      <button
                        key={view}
                        onClick={() => c.setFilterView(view)}
                        className={`px-3 py-1.5 rounded-pill border text-xs font-medium transition-colors ${
                          c.filterView === view 
                            ? 'bg-surface-hover text-text-primary border-border-default' 
                            : 'bg-transparent text-text-secondary border-transparent hover:bg-surface-hover/50'
                        }`}
                      >
                        {label}
                      </button>
                    )
                  })}
                </div>
                <div className="flex items-center gap-3">
                   {!c.isBatchMode && (
                     <button
                       onClick={() => c.setIsBatchMode(true)}
                       className="flex items-center gap-1.5 text-text-secondary hover:text-text-primary text-xs"
                     >
                       <Square size={14} /> 进入批量选择
                     </button>
                   )}
                  {c.flags.followRunning && c.isTaskRunning && (
                    <button
                      onClick={() => c.setFollowPaused((v) => !v)}
                      className="flex items-center gap-1 px-2 py-1 rounded-pill text-xs border border-border-default hover:bg-surface-hover transition-colors text-text-secondary"
                    >
                      {c.followPaused ? <><Eye size={12} /> 恢复跟随</> : <><EyeOff size={12} /> 暂停跟随</>}
                    </button>
                  )}
                </div>
              </div>
```

- [ ] **Step 2: Connect Hero props**

```tsx
// Update TodayHero usage in TodayTasksV2.tsx:
      <TodayHero
        isTaskRunning={c.isTaskRunning}
        // ... existing props ...
        filteredCount={c.filteredItemsCount}
        filterView={c.filterView}
        onRetryFailures={c.statusCounts.error > 0 ? () => c.handleProcess(c.items.filter(it => c.rowStatusMap[(it.voc_spelling||'').toLowerCase()]?.status === 'error').map(it => it.voc_id)) : undefined}
      />
```

- [ ] **Step 3: Commit**

```bash
git add web/frontend/src/pages/TodayTasksV2.tsx
git commit -m "feat(today): add advanced filter bar and connect to hero"
```

### Task 4: Inline Status Animations and Error Handling

Update the table row rendering to include pulse animation for running tasks and inline retry for errors.

**Files:**
- Modify: `web/frontend/src/pages/TodayTasksV2.tsx`

- [ ] **Step 1: Add row interactions (Pulse & Checkboxes)**

```tsx
// Inside the table body mapping:
                    const isError = status === 'error'
                    const isSelected = c.selectedIds.has(item.voc_id)

                    return (
                      <tr
                        key={item.voc_id}
                        onClick={c.isBatchMode ? () => {
                          const next = new Set(c.selectedIds)
                          if (next.has(item.voc_id)) next.delete(item.voc_id)
                          else next.add(item.voc_id)
                          c.setSelectedIds(next)
                        } : undefined}
                        className={`border-t border-border-soft transition-all duration-300 ${
                          c.isBatchMode ? 'cursor-pointer' : ''
                        } ${
                          isRunning ? 'bg-surface-highlight animate-pulse' : 
                          isError ? 'bg-error-soft/30' : 'hover:bg-surface-hover'
                        }`}
                        // ... ref ...
                      >
                        {c.isBatchMode && (
                          <td className="px-4 py-2 w-10">
                            <input 
                              type="checkbox" 
                              checked={isSelected} 
                              readOnly
                              className="w-4 h-4 rounded border-border-default text-accent focus:ring-accent/20" 
                            />
                          </td>
                        )}
                        <td className="px-4 py-2 text-text-muted w-12">{i + 1}</td>
```

- [ ] **Step 2: Add inline retry button for errors**

```tsx
// At the end of the row (add a new td):
                        <td className="px-4 py-2 text-right">
                           {isError && !c.isBatchMode && (
                             <button
                               onClick={(e) => { e.stopPropagation(); c.handleProcess([item.voc_id]) }}
                               className="text-error hover:text-error/80 text-xs px-2 py-1 rounded border border-error/30 hover:bg-error-soft transition-colors"
                             >
                               ↻ 重试
                             </button>
                           )}
                        </td>
```

- [ ] **Step 3: Commit**

```bash
git add web/frontend/src/pages/TodayTasksV2.tsx
git commit -m "feat(today): add running row pulse animation and inline error retry"
```

### Task 5: Floating Bottom Bar for Batch Mode

Create the `BottomBar` component and integrate it to handle batch operations.

**Files:**
- Create: `web/frontend/src/components/today/BottomBar.tsx`
- Modify: `web/frontend/src/pages/TodayTasksV2.tsx`

- [ ] **Step 1: Create BottomBar component**

```tsx
import React from 'react'

export interface BottomBarProps {
  selectedCount: number
  onCancel: () => void
  onProcess: () => void
  disabled?: boolean
}

export default function BottomBar({ selectedCount, onCancel, onProcess, disabled }: BottomBarProps) {
  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 transform transition-transform duration-300 translate-y-0">
      <div className="bg-surface-card border-t border-border-default shadow-lg p-4 flex items-center justify-between max-w-5xl mx-auto rounded-t-xl">
        <div className="flex items-center gap-4">
          <span className="text-text-primary font-medium">已选择 {selectedCount} 个词</span>
          <button 
            onClick={onCancel}
            className="text-text-secondary hover:text-text-primary text-sm px-3 py-1.5 rounded-button hover:bg-surface-hover transition-colors"
          >
            取消选择
          </button>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={onProcess}
            disabled={disabled || selectedCount === 0}
            className="bg-accent text-white px-6 py-2 rounded-button text-sm font-medium hover:bg-accent-hover disabled:opacity-50 transition-colors shadow-sm"
          >
            🚀 处理选中项
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Integrate BottomBar into TodayTasksV2**

```tsx
// Import BottomBar
import BottomBar from '../components/today/BottomBar'

// Add to the bottom of the component (outside the main container flow, but inside the return):
      {c.isBatchMode && (
        <BottomBar
          selectedCount={c.selectedIds.size}
          onCancel={() => {
            c.setIsBatchMode(false)
            c.setSelectedIds(new Set())
          }}
          onProcess={() => {
            c.handleProcess(Array.from(c.selectedIds))
            c.setIsBatchMode(false)
            c.setSelectedIds(new Set())
          }}
          disabled={c.processing}
        />
      )}
```

- [ ] **Step 3: Commit**

```bash
git add web/frontend/src/components/today/BottomBar.tsx web/frontend/src/pages/TodayTasksV2.tsx
git commit -m "feat(today): implement floating bottom bar for batch selection mode"
```
