# V1 任务单（C02 + C03）

更新时间：2026-05-02（v2 修订：插入 T0、拆分 T6、明确文件边界与门禁口径）
目标：不影响日常 Today 使用前提下，落地 Today 主闭环与失败分组重试
范围：仅任务拆分，不执行代码修改

---

## 0. 输入文档

1. `docs/dev/web_ui/WEB_UI_EXEC_PLAN.md`
2. `docs/dev/web_ui/WEB_UI_EXECUTION_PLAN_V1.md`
3. `docs/dev/web_ui/chapters/C02_TODAY_COMMAND_CENTER.md`
4. `docs/dev/web_ui/chapters/C03_FAILURE_GROUPS_AND_RETRY.md`
5. `docs/dev/web_ui/chapters/GLOBAL_TODAY_GUARDRAILS.md`

---

## 0.1 v2 修订说明

v1 任务单存在 5 处落地阻塞：

1. 缺 feature flag 体系（T9 立项前任何 T1-T8 都没法 behind flag）
2. 缺组级重试后端入口（T6 前端无 API 可用）
3. 缺 error_type/error_code 协议字段（T5 分组无稳定键）
4. 没有"Today 冒烟 E2E"实测用例（T10 门禁口径无法判定）
5. A/B 组并行会撞 `TodayTasks.tsx` 单文件

v2 修订：

1. 插入 T0 作为前置任务，含 flag 骨架 + RowState 协议扩展
2. T6 拆分为 T6a（后端入口）+ T6b（前端动作）
3. 明确文件边界（A 组 / B 组各自独立目录）
4. 门禁口径定为 (a) 后端 pytest + (b) 前端 Vitest 纯函数单测
5. 列出 V1 近似实现项与延期到 C08 的契约升级项

---

## 1. V1 验收口径（完成定义）

V1 完成必须同时满足：

1. Today 默认行为：行视图优先 + 默认仅可执行项
2. 执行链路可用：轻确认条 -> 执行 -> 跟随当前行 -> 完成停留摘要
3. 失败闭环可用：失败分组 -> 组级重试 -> >100 条二次确认 -> 失败残留高亮
4. 不影响日常使用：全局门禁通过（pytest tests/web/ + 前端 Vitest + build/typecheck）
5. 支持快速回退：新增交互受 feature flag 控制，提供一键全关回退

---

## 2. 文件边界（强制，避免 A/B 组冲突）

| 组 | 边界范围 | 备注 |
| --- | --- | --- |
| 公共 | `web/frontend/src/utils/featureFlags.ts` | T0 创建，T9 收口 |
| 公共 | `web/backend/schemas.py` + `web/frontend/src/api/types.ts` | T0/T6a 各自扩展不同字段，避免重叠 |
| A 组 | `web/frontend/src/pages/TodayTasks.tsx`（外壳） | A 组独占。挂点为 B 组面板预留 props，由 A 组负责挂载 |
| A 组 | `web/frontend/src/components/today/LightConfirmBar.tsx`（新） | T2 |
| A 组 | `web/frontend/src/components/today/SummaryPanel.tsx`（新） | T4 |
| A 组 | `web/frontend/src/utils/todayView.ts`（新，纯函数） | T1/T3 筛选/排序/跟随逻辑 |
| B 组 | `web/frontend/src/components/today/FailureGroupsPanel.tsx`（新） | T5/T6b/T7/T8 |
| B 组 | `web/frontend/src/utils/failureGrouping.ts`（新，纯函数） | T5 分组算法 |
| B 组 | `web/backend/routers/study.py` + 相关测试 | T6a |

并行约束：

1. T0 必须先单独落地，A/B 组都依赖 flag 工具与协议字段
2. A 组 T1-T4 与 B 组 T5/T8 可在 T0 完成后并行
3. T6a 后端入口落地后 T6b 才能动
4. T9/T10 串行收尾

---

## 3. V1 近似实现声明

以下行为在 V1 用近似实现，正式契约升级排到 C08：

| 项 | V1 近似 | 正式契约（延期） |
| --- | --- | --- |
| "可执行项"筛选 | `phase != 'skipped' && status != 'done'`，事件未到达视为可执行 | TodayItem 增加 `executable: bool` 字段 |
| "价值优先"排序 | `familiarity_short ASC, review_count DESC` | TodayItem 增加 `value_score: float` 字段 |
| "时间压力"次级排序 | 沿用 `review_count DESC` 作为代理 | 引入显式截止字段 |
| `error_type`/`error_code` | 后端先留空字段，前端 fallback 用 `phase` 兜底 | 后端 workflow 改造，发射结构化错误码 |
| 自动跟随行 | 跟随首个 `status==='running'` 的行 | 多并发 running 时的优先级策略 |

---

## 4. 任务拆分（v2 修订版）

## T0. Feature flag 骨架 + 类型契约扩展（前置）

目标：先把 flag 工具与协议字段铺好，避免后续任务回头改协议。

产出：

1. `web/frontend/src/utils/featureFlags.ts`：env（`VITE_FF_*`） + URL（`?ff_xxx=on`） + localStorage（`ff_xxx`）三层覆盖；提供 `isEnabled(key)` 与 `disableAll()`
2. `web/backend/schemas.py` 中 `RowState` 新增 `error_type: Optional[str]` 与 `error_code: Optional[str]`，默认 `None`
3. 重新生成 `web/frontend/src/api/types.ts`（运行 `npm run gen:types`）
4. 后端发射端不在本任务实际填充 `error_type`/`error_code`（保持 V1 不破坏现有路径），仅扩协议
5. flag 默认值表写入 `featureFlags.ts` 文件头注释

验收：

1. `featureFlags.ts` 单测覆盖三层覆盖优先级
2. 协议字段在 schemas.py 与 types.ts 一致
3. 后端 pytest 现有用例全绿（不应破坏旧契约）

风险：

1. 协议扩展导致客户端旧代码报错 -> 字段 Optional + 默认 None 保证向后兼容

回退：

1. 移除 featureFlags.ts 与 RowState 新字段，重生成 types.ts

## T1. Today 列表默认态改造

flag：`ff_today_default_view`
目标：实现 C02 默认展示与排序筛选语义。

产出：

1. 行视图默认渲染（沿用现有表格，结构调整）
2. 默认筛选"仅可执行项"（V1 近似见 §3）
3. 排序"价值优先 + 时间压力次级"（V1 近似见 §3）
4. "查看全部"快速切换入口
5. 筛选/排序逻辑写入 `utils/todayView.ts`（纯函数，便于 T10 单测）

验收：

1. 首次进入 Today 即满足默认态
2. 切换"查看全部"不影响数据正确性
3. flag 关闭时回退旧行为

## T2. 执行前轻确认条

flag：`ff_today_light_confirm`
目标：执行前显示非弹窗轻确认信息。

### T2 实现任务拆分

#### T2.1 新建 LightConfirmBar 组件

文件：`web/frontend/src/components/today/LightConfirmBar.tsx`

Props 接口：

```tsx
interface LightConfirmBarProps {
  /** 本次将执行的条目数量 */
  count: number
  /** 用户确认执行 */
  onConfirm: () => void
  /** 用户取消（收起确认条） */
  onCancel: () => void
  /** 是否正在执行中（确认后变为 loading 态） */
  loading?: boolean
}
```

组件行为：

1. 渲染为一行内联横条（非弹窗、非 Modal），插入在"全部处理"按钮下方
2. 左侧文案：`"本次将执行 {count} 条，可随时停止"`
3. 右侧双按钮：`"确认执行"` + `"取消"`
4. 确认后按钮变为 loading 态（disabled + Loader2 旋转图标），文案切换为 `"执行中…"`
5. 视觉风格：蓝色 info bar 背景（`bg-blue-50 border border-blue-200 rounded-lg`），与现有 error bar（`bg-red-50`）对齐
6. 过渡动画：进入时下滑展开（CSS `transition-all`），取消时收起

复用设计（为 T6b 预留）：

- T6b 组级重试也需要"将重试 N 条"确认条，LightConfirmBar 的 `count` + 文案可由外部 slot 或 `message` prop 自定义
- 增加可选 `message?: string` prop，缺省时使用默认文案 `"本次将执行 {count} 条，可随时停止"`

#### T2.2 TodayTasks.tsx 集成确认流程

文件：`web/frontend/src/pages/TodayTasks.tsx`（A 组独占）

状态机：在 TodayTasks 中引入执行阶段状态：

```
idle → confirming → executing → idle
         ↓ (cancel)
        idle
```

具体改动：

1. 新增状态 `const [confirmingProcess, setConfirmingProcess] = useState(false)`
2. 修改"全部处理"按钮 `onClick`：
   - flag ON 时：`setConfirmingProcess(true)`（显示确认条，不立即执行）
   - flag OFF 时：直接调用 `handleProcess()`（保持旧行为）
3. 在按钮下方条件渲染 `<LightConfirmBar>`：
   - `count` = `executableItems.length`（T1 已算好的可执行项数量）
   - `onConfirm` = `handleProcess` → 触发执行 + `setConfirmingProcess(false)`
   - `onCancel` = `setConfirmingProcess(false)`
   - `loading` = `processing`（执行中的 loading 态）
4. 确认条可见时，"全部处理"按钮 disabled（避免重复点击）

#### T2.3 Flag 守卫

文件：`web/frontend/src/pages/TodayTasks.tsx`

```tsx
const lightConfirmEnabled = isEnabled('ff_today_light_confirm')
```

- `lightConfirmEnabled === true`：按钮点击 → 显示确认条 → 用户确认 → 执行
- `lightConfirmEnabled === false`：按钮点击 → 直接执行（当前旧行为，不渲染 LightConfirmBar）

#### T2.4 边界用例处理

1. **count === 0**：不应到达确认条（按钮已 disabled），但 LightConfirmBar 内部也做兜底：count ≤ 0 时不渲染
2. **执行中再次点击**：按钮已 disabled + 确认条 loading 态，双重防御
3. **执行完成/失败**：`processing` 变为 false 时，确认条自动消失（`confirmingProcess` 在 `handleProcess` finally 中重置）
4. **列表刷新**：确认条显示期间列表数据刷新导致 count 变化时，确认条实时反映最新 count

#### T2.5 验证清单

1. `npm --prefix web/frontend run build` 通过（typecheck）
2. 手动验证场景：
   - flag ON：点击"全部处理" → 出现确认条 → 点确认 → 执行 → 确认条消失
   - flag ON：点击"全部处理" → 出现确认条 → 点取消 → 确认条消失，不执行
   - flag OFF：点击"全部处理" → 直接执行，无确认条
3. 确认条 count 与 T1 筛选条中 `仅可执行 (N)` 的 N 一致

### T2 产出文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `web/frontend/src/components/today/LightConfirmBar.tsx` | 新建 | 轻确认条组件 |
| `web/frontend/src/pages/TodayTasks.tsx` | 修改 | 集成确认流程 + flag 守卫 |

### T2 验收

1. 点击执行前可见确认条
2. count 与实际可执行数量一致
3. flag 关闭时直接执行无确认条
4. 取消后不执行、确认条消失
5. build + typecheck 通过

### T2 风险与回退

风险：确认条增加一步操作可能影响效率 → 通过 flag 关闭即可跳过
回退：关闭 `ff_today_light_confirm`，按钮直接执行


## T3. 执行中交互稳定化

flag：`ff_today_follow_running`
目标：执行中不打断主流程。

### T3 实现任务拆分

#### T3.1 行 ref 注册与滚动机制

文件：`web/frontend/src/pages/TodayTasks.tsx`

技术方案：

1. 使用 `useRef<Map<string, HTMLTableRowElement>>()` 维护每行 DOM 引用
2. 在 `<tr>` 渲染时通过 ref callback 注册：`ref={el => { if (el) rowRefs.current.set(key, el); else rowRefs.current.delete(key) }}`
3. key 使用 `item.voc_spelling.toLowerCase()` 与 `rowStatusMap` / `findRunningKey` 一致

滚动调用：

```tsx
const scrollToRow = (key: string) => {
  const el = rowRefs.current.get(key)
  el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}
```

- `block: 'center'`：将目标行滚动到视口中央，避免贴顶/贴底
- `behavior: 'smooth'`：平滑滚动，不突兀

#### T3.2 useEffect 跟随驱动

文件：`web/frontend/src/pages/TodayTasks.tsx`

利用 T1 已有的 `findRunningKey`（`todayView.ts`）：

```tsx
const followRunningEnabled = isEnabled('ff_today_follow_running')
const [followPaused, setFollowPaused] = useState(false)

const runningKey = useMemo(() => findRunningKey(rowStatusMap), [rowStatusMap])

useEffect(() => {
  if (!followRunningEnabled || followPaused || !runningKey) return
  scrollToRow(runningKey)
}, [followRunningEnabled, followPaused, runningKey])
```

行为：
- 每当 `runningKey` 变化（新的一行进入 running 状态），自动滚动到该行
- SSE 事件流中 `row_status` 事件推送 → `events` 变化 → `rowStatusMap` 重算 → `runningKey` 更新 → useEffect 触发滚动
- 不应在同一 `runningKey` 重复滚动（useEffect 依赖 `runningKey` 变化即可天然去重）

#### T3.3 暂停跟随交互

文件：`web/frontend/src/pages/TodayTasks.tsx`

C02 §6.2 要求"提供暂停跟随开关"：

1. 新增状态 `const [followPaused, setFollowPaused] = useState(false)`
2. 仅在执行中（`taskStatus` 为 `running` 或 `pending`）且 flag ON 时显示暂停/恢复按钮
3. 位置：在 T1 筛选条右侧添加"暂停跟随"/"恢复跟随"切换按钮
4. 视觉：小型文字按钮，用 `Eye` / `EyeOff` 图标（lucide）
5. 任务终态（`done` / `error`）时自动重置 `followPaused = false`

```tsx
// 任务终态时重置暂停状态
useEffect(() => {
  if (taskStatus === 'done' || taskStatus === 'error' || taskStatus === 'idle') {
    setFollowPaused(false)
  }
}, [taskStatus])
```

#### T3.4 执行中筛选提示

文件：`web/frontend/src/pages/TodayTasks.tsx`

C02 §6.3 要求"在筛选区域明确提示仅影响显示"：

1. 当 `taskStatus` 为 `running` 或 `pending`（执行中）时，在 T1 筛选条下方显示提示
2. 文案：`"筛选仅影响显示，不影响正在执行的任务"`
3. 视觉：`text-xs text-amber-600`，使用 `Info` 图标
4. 不在执行中时不显示此提示

实现说明：
- 当前后端 `POST /api/study/process` 是全量处理（不受前端筛选影响），所以执行中改筛选确实仅影响显示
- 此提示是认知引导，避免用户误以为改筛选会改变执行集合

#### T3.5 验证清单

1. `npm --prefix web/frontend run build` 通过（typecheck）
2. `npx vitest run` 全绿（不应破坏既有 37 个测试）
3. 手动验证场景：
   - flag ON + 执行中：列表自动滚动到 running 行
   - 点"暂停跟随"后不再自动滚动，点"恢复跟随"恢复
   - 执行中改筛选，提示"仅影响显示"可见
   - 任务完成后暂停状态自动重置
   - flag OFF：无自动滚动、无暂停按钮

### T3 产出文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `web/frontend/src/pages/TodayTasks.tsx` | 修改 | 集成自动跟随 + 暂停开关 + 筛选提示 |

说明：`findRunningKey` 已在 T1 中实现于 `utils/todayView.ts`，T3 无需修改该文件。

### T3 验收

1. 执行中滚动行为稳定
2. 改筛选不改变执行任务集合
3. flag 关闭时不滚动
4. 暂停跟随可用且终态自动重置
5. 执行中筛选提示可见

### T3 风险与回退

风险：自动滚动影响手动查看 → 暂停跟随开关
风险：频繁滚动闪烁 → `runningKey` 天然去重，只在切换行时滚动
回退：关闭 `ff_today_follow_running`


## T4. 完成后摘要停留

flag：`ff_today_summary_stay`
目标：任务完成后停留在结果摘要区。

### T4 实现任务拆分

#### T4.1 新建 SummaryPanel 组件

文件：`web/frontend/src/components/today/SummaryPanel.tsx`

Props 接口：

```tsx
interface SummaryPanelProps {
  /** 成功（done）条目数 */
  doneCount: number
  /** 失败（error）条目数 */
  errorCount: number
  /** 跳过（skipped）条目数 */
  skippedCount: number
  /** 总条目数 */
  totalCount: number
  /** 任务终态类型：done / error / canceled */
  taskStatus: string
  /** 点击"进入失败分组"（联动 T5，T5 未完成时为 undefined） */
  onGoToFailures?: () => void
}
```

组件行为：

1. 渲染为卡片面板，显示在列表上方
2. 顶部状态标题：
   - `done` → "✅ 任务完成" (绿色)
   - `error` → "⚠️ 任务异常终止" (红色)
   - `canceled` → "🚫 任务已取消" (灰色)
3. 统计行：三列数字卡片
   - 成功 N 条 (绿色 badge)
   - 失败 N 条 (红色 badge)
   - 跳过 N 条 (灰色 badge)
4. 底部操作区：
   - "进入失败分组" 按钮（errorCount > 0 且 onGoToFailures 存在时可点击）
   - T5 未实现前，按钮显示为 disabled 状态 + 提示"失败分组功能开发中"
5. 视觉风格：与现有 error bar / LightConfirmBar 一致的圆角卡片

统计计算逻辑（从 rowStatusMap 中提取，在 TodayTasks 中计算后传入）：

```tsx
// 在 TodayTasks.tsx 中
const statusCounts = useMemo(() => {
  let done = 0, error = 0, skipped = 0
  for (const s of Object.values(rowStatusMap)) {
    if (s.phase === 'skipped') skipped++
    else if (s.status === 'done') done++
    else if (s.status === 'error') error++
  }
  return { done, error, skipped }
}, [rowStatusMap])
```

#### T4.2 TodayTasks.tsx 集成

文件：`web/frontend/src/pages/TodayTasks.tsx`

显示条件：

```tsx
const summaryStayEnabled = isEnabled('ff_today_summary_stay')
const isTerminal = taskStatus === 'done' || taskStatus === 'error' || taskStatus === 'canceled'
const showSummary = summaryStayEnabled && isTerminal && items.length > 0
```

渲染位置：在列表上方、筛选条下方插入 `<SummaryPanel>`。

行为：
- 终态时展示摘要面板（不隐藏列表，用户仍可向下查看详情）
- flag 关闭时不渲染 SummaryPanel，维持旧行为

#### T4.3 失败分组联动入口（T5 预留）

SummaryPanel 的 `onGoToFailures` prop：
- T5 未实现时传 `undefined`，按钮显示为 disabled + "即将推出"
- T5 完成后，传入跳转到 FailureGroupsPanel 的回调

#### T4.4 验证清单

1. `npm --prefix web/frontend run build` 通过
2. `npx vitest run` 全绿
3. 手动验证场景：
   - flag ON + 任务完成 → 出现摘要面板，统计正确
   - flag ON + 任务失败 → 出现摘要面板，"进入失败分组"按钮可见（disabled）
   - flag OFF → 无摘要面板
   - 终态后列表仍然可见（不跳到顶部）

### T4 产出文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `web/frontend/src/components/today/SummaryPanel.tsx` | 新建 | 摘要面板组件 |
| `web/frontend/src/pages/TodayTasks.tsx` | 修改 | 集成摘要面板 + flag 守卫 |

### T4 验收

1. 终态后不跳到列表顶部
2. 可直接进入失败分组处理（T5 完成后激活）
3. flag 关闭时无摘要面板
4. 统计数字与行状态一致

### T4 风险与回退

风险：摘要面板占用空间影响列表查看 → 面板在列表上方，不遮挡
回退：关闭 `ff_today_summary_stay`


## T5. 失败分组构建

flag：`ff_today_failure_groups`
目标：实现 C03 分组语义。

### T5 实现任务拆分

#### T5.1 新建工具类 `failureGrouping.ts`

文件：`web/frontend/src/utils/failureGrouping.ts`
测试：`web/frontend/src/utils/failureGrouping.test.ts`

逻辑：
1. 提取所有 `status === 'error'` 的项
2. 分组 Key 策略：优先 `error_type`，其次 `error_code`，兜底 `phase`（格式如 `type:NETWORK` 或 `code:404` 或 `phase:gen_story`）。T0 已经扩展了后端协议，RowState 包含 `error_type` 和 `error_code`。
3. 聚合：`Record<string, FailureGroup>`，每个 group 包含 `groupKey`, `label`（友好展示名）, `reason`（代表性原因）, `items`（原始条目数组）
4. 排序：按 `items.length` 降序排列返回数组

```tsx
export interface FailureGroup {
  groupKey: string
  label: string
  reason: string
  items: TodayItem[]
}
export function buildFailureGroups(items: TodayItem[], rowStatusMap: Record<string, RowState>): FailureGroup[]
```

#### T5.2 新建组件 `FailureGroupsPanel.tsx`

文件：`web/frontend/src/components/today/FailureGroupsPanel.tsx`

Props：
```tsx
interface FailureGroupsPanelProps {
  groups: FailureGroup[]
  rowStatusMap: Record<string, RowState>
  onRetryGroup?: (group: FailureGroup) => void // T6b 预留
  onBack: () => void // 返回完整列表
}
```

UI 行为：
1. 顶部提供返回按钮："← 返回完整列表"
2. 如果 `groups.length === 0`，渲染空状态。
3. 渲染每组为一个可折叠的卡片（accordion）。
4. **默认展开第一个分组**（即失败数量最多的组）。
5. 每组卡片头部显示：Label、Reason 截断、数量 Badge、"重试本组 N 项"按钮（当前 T5 阶段该按钮 disabled，提示"T6b 开发中"）。
6. 每组展开内容：展示该组下的单词列表（类似主列表的精简版）。

#### T5.3 TodayTasks.tsx 页面集成

文件：`web/frontend/src/pages/TodayTasks.tsx`

集成逻辑：
1. 新增状态 `const [showFailureMode, setShowFailureMode] = useState(false)`
2. 在 `SummaryPanel` 的 `onGoToFailures` 传参：`() => setShowFailureMode(true)`
3. 当 `showFailureMode === true` 且 `ff_today_failure_groups` 开启时，隐藏原主列表 `<table ...>`，渲染 `<FailureGroupsPanel>`。
4. 传递 `onBack={() => setShowFailureMode(false)}`

#### T5.4 验证清单

1. `npx vitest run`：`failureGrouping.test.ts` 纯函数测试通过（分组、降序排列）
2. 手动验证：
   - 执行结束有失败时，点击 SummaryPanel 的"进入失败分组"按钮可切换视图
   - 视图中正确渲染失败组，默认展开第一个
   - 重试按钮占位显示正确
   - 点返回可回到完整列表

### T5 产出文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `web/frontend/src/utils/failureGrouping.ts` | 新建 | 核心分组逻辑 |
| `web/frontend/src/utils/failureGrouping.test.ts` | 新建 | 单测 |
| `web/frontend/src/components/today/FailureGroupsPanel.tsx` | 新建 | 分组列表视图 |
| `web/frontend/src/pages/TodayTasks.tsx` | 修改 | 集成视图切换 |

### T5 验收

1. 分组稳定且可复现（同输入同输出）
2. 排序与默认展开符合规则
3. flag 关闭时不渲染失败分组面板

### T5 风险与回退

风险：后端未传详细 error_type 导致全部分到兜底组 → 前端逻辑正常兜底为 phase，无 crash 风险
回退：关闭 `ff_today_failure_groups`

## T6a. 后端组级重试入口

目标：扩展后端入口接受 voc_id 子集。

### T6a 实现任务拆分

#### T6a.1 定义 ProcessRequest Schema
文件：`web/backend/schemas.py`

```python
class ProcessRequest(BaseModel):
    voc_ids: Optional[List[str]] = Field(default=None, description="Optional list of vocabulary IDs to process. If empty, process all pending.")
```

#### T6a.2 修改 POST /api/study/process
文件：`web/backend/routers/study.py`

将 `process_today_words` 修改为接受 `request: ProcessRequest = Body(default_factory=ProcessRequest)`。
如果 `request.voc_ids` 为空，沿用旧路径（调用 `momo.get_today_items` 并在未完成时提取 id）；
如果 `request.voc_ids` 非空，则仅过滤出 `voc_ids` 的部分，传给 `process_word_list`。

#### T6a.3 同步前端类型
文件：`web/frontend/src/api/types.ts`
运行生成脚本：`python scripts/generate_frontend_types.py`，确保 `ProcessRequest` 反映到前端。

#### T6a.4 完善后端验证测试
文件：`tests/web/test_v1_acceptance.py`（如果已有类似测试，则在其内扩展；否则可新建/修改对应路由测试 `tests/web/test_study_router.py`）

确保：
1. 不传 body 时旧行为不变。
2. 传 `voc_ids` 时仅执行对应的词。
3. 传不存在的 `voc_ids` 不崩溃。

## T6b. 前端组级重试动作

flag：`ff_today_group_retry`
目标：实现组级全量重试链路。

### T6b 实现任务拆分

#### T6b.1 TodayTasks.tsx 支持重试参数
文件：`web/frontend/src/pages/TodayTasks.tsx`

修改 `handleProcess` 签名，接受可选的 `voc_ids?: string[]`：
```tsx
const handleProcess = async (voc_ids?: string[]) => {
  setProcessing(true)
  try {
    const payload = voc_ids ? { voc_ids } : {}
    const res = await apiPost<TaskSubmitResponse>('/api/study/process', payload)
    if (res.data?.task_id) {
      setActiveTask(res.data.task_id)
    }
  } catch (e) { ... }
}
```

#### T6b.2 集成轻确认条到 FailureGroupsPanel
文件：`web/frontend/src/components/today/FailureGroupsPanel.tsx`

1. 传入 `ff_today_group_retry` 控制逻辑。
2. 添加状态 `const [confirmingGroup, setConfirmingGroup] = useState<string | null>(null)`。
3. 点击"重试本组"按钮时，如果 flag ON，则将该组的 groupKey 存入 `confirmingGroup`。如果 flag OFF，按钮应该不可见或 disabled。
4. 如果 `confirmingGroup === g.groupKey`，在原按钮位置（或卡片下方）展示 `LightConfirmBar`（复用 T2 组件）。
5. 传给 LightConfirmBar 的 Props：
   - `count={g.items.length}`
   - `message={\`将重试本组 ${g.items.length} 个单词\`}`
   - `onCancel={() => setConfirmingGroup(null)}`
   - `onConfirm={() => { onRetryGroup?.(g); setConfirmingGroup(null); }}`

#### T6b.3 联调验证
1. `npx vitest run` 和 `pytest` 跑通。
2. 前端界面：点击"重试本组" -> 展开轻确认条 -> 确认 -> 触发重试（仅发送这部分 ids） -> 列表随之响应 `row_status` 并更新 UI。

### T6 验收
1. 重试范围正确（仅该组 `voc_ids` 被发送和处理）
2. 后端不阻断原本全量处理的无参调用
3. flag 关闭时重试按钮不可用

## T7. 大批量二次确认门禁

flag：`ff_today_bulk_guard`（默认 ON，独立于其他 flag）
目标：避免误触发大规模重试。

### T7 实现任务拆分

#### T7.1 featureFlags 扩展
文件：`web/frontend/src/utils/featureFlags.ts`

1. 导出常量 `export const BULK_RETRY_THRESHOLD = 100`
2. 确保 `ff_today_bulk_guard` 定义存在且默认为 `true`。

#### T7.2 TodayTasks.tsx 支持全部处理防误触
文件：`web/frontend/src/pages/TodayTasks.tsx`

1. 引入 `BULK_RETRY_THRESHOLD`。
2. 在点击"全部处理"时，如果 `data.count > BULK_RETRY_THRESHOLD` 且 `ff_today_bulk_guard` 开启，则不仅触发 `LightConfirmBar`，还可以使 `LightConfirmBar` 接收一个 `warning` 级别，显示特别的高亮警告（例如红色按钮，或弹窗模式）。为了简单起见，可以给 `LightConfirmBar` 增加 `variant="default" | "danger"` 属性，或者单独在页面用一个原生的 `window.confirm` 或自定义 `Modal` 进行二次确认。
*考虑到这是一个严肃的二次弹窗，我们可以新建一个简单的 `BulkGuardModal.tsx`，或者在 `TodayTasks.tsx` 和 `FailureGroupsPanel.tsx` 共享。*

为了复用，我们在 `components/today` 下新建 `BulkGuardModal.tsx`：
```tsx
interface Props {
  count: number;
  onConfirm: () => void;
  onCancel: () => void;
}
// 包含文案："注意：您即将重试 {count} 个单词，这可能会消耗较多系统资源和时间。是否确认继续？"
```

#### T7.3 FailureGroupsPanel 集成
文件：`web/frontend/src/components/today/FailureGroupsPanel.tsx`

1. 点击"重试本组"时，如果数量 `> BULK_RETRY_THRESHOLD` 且 `isEnabled('ff_today_bulk_guard')` 为 true：
   - 不显示内联 `LightConfirmBar`，而是弹出 `BulkGuardModal` 弹窗。
2. 弹窗点确认后才触发真正的 `onRetryGroup`。
3. `<= 100` 则走原来的 `LightConfirmBar`。

### T7 验收
1. <=100 时仍然使用轻确认条（对于全部处理或组内重试）
2. >100 时触发醒目的 `BulkGuardModal` 拦截
3. `ff_today_bulk_guard` 设为 false 后，即使 >100 也降级走普通轻确认条

## T8. 残留失败高亮

flag：`ff_today_residual_highlight`
目标：重试后仍失败项可直接定位。

### T8 实现任务拆分

#### T8.1 featureFlags 扩展
文件：`web/frontend/src/utils/featureFlags.ts`
（其实 `ff_today_residual_highlight` 已经存在于 V1_FLAGS 中，只需在组件中使用）

#### T8.2 FailureGroupsPanel 中高亮残留失败项
文件：`web/frontend/src/components/today/FailureGroupsPanel.tsx`

1. 引入 `isEnabled('ff_today_residual_highlight')`。
2. 在渲染分组的单词列表 `<tr>` 时，如果 `state.status === 'error'` 且该 flag 开启：
   - 给整行 `<tr>` 加上浅红色背景（如 `bg-red-50`）或左侧红色边框（如 `border-l-4 border-l-red-500`），以使其在重试过程中或重试后一眼能识别出"这是一个失败项"。
   - 考虑到原本在 FailureGroupsPanel 里的项可能都是 error，但在重试时它们会变成 `pending` 或 `running`。重试结束后，仍为 `error` 的项会再次显现为高亮，而成功的项会从列表消失（由于被重新分组或由于不再是 error 导致过滤，取决于我们分组时是否排除了成功项，当前 `buildFailureGroups` 已经过滤了 `status === 'error'` 的项，所以成功的项会直接消失）。
   - 如果成功的项消失，残留的高亮项仍然会保留。

### T8 验收
1. 错误项在 `FailureGroupsPanel` 中具有明显的视觉高亮（例如红底或红左边框）。
2. `ff_today_residual_highlight` 关闭时，恢复普通白底。

## T9. Feature Flag 总开关与回退

目标：保证 V1 可快速回退。

产出：

1. 所有 V1 flag 在 `featureFlags.ts` 集中维护，含默认值表
2. 一键全关：URL `?ff_off=v1` 或 localStorage 设置 `ff_off=v1`
3. 文档化开关说明（在 `featureFlags.ts` 文件头）

验收：

1. 关闭 flag 后 Today 回到 v1 修订前的稳定行为
2. 无残留异常状态
3. 一键全关生效

## T10. 验证与发布准备

目标：合入前完成门禁与说明。

门禁口径（已确认）：

1. **(a) 后端 pytest**：`python -m pytest tests/web/ -v -m "not slow"` 全绿
   - 必含 `test_study.py`、`test_tasks_api.py`、`test_v1_acceptance.py`（T6a 新增）
2. **(b) 前端单测**：引入 Vitest，覆盖 `utils/todayView.ts`、`utils/failureGrouping.ts`、`utils/featureFlags.ts` 三个纯函数文件
   - 命令：`npm --prefix web/frontend run test`
3. **build + typecheck**：`npm --prefix web/frontend run build`（已含 `tsc -b`）

产出：

1. 三项门禁运行结果（命令 + 摘要）
2. 风险与回退说明
3. flag 默认值清单
4. CHANGELOG 同步

验收：

1. 三项门禁全通过
2. 验收记录完整

---

## 5. 建议执行顺序

1. **串行前置**：T0
2. **并行**：A 组（T1->T2->T3->T4） 与 B 组（T5->T8 + T6a）
3. **依赖收尾**：T6b（依赖 T6a + T2）-> T7（依赖 T5）-> T9 -> T10

依赖关系：

- T1-T8 全部依赖 T0
- T6b 依赖 T6a 与 T2
- T7 依赖 T5
- T8 依赖 T6b
- T9 依赖 T1-T8
- T10 依赖 T9

---

## 6. 交付清单模板（每个任务）

1. 任务编号
2. 改动文件列表
3. 变更说明（3-6 条）
4. 风险与回退方式
5. 验证命令与结果

---

## 7. 给执行者的硬约束

1. 不得破坏 Today 日常可用性（GLOBAL_TODAY_GUARDRAILS）
2. 不得跳过全局门禁
3. 无验证证据不得声称完成
4. 发现跨模块风险要先停并上报
5. 任何超出 T0-T10 的范围扩展都要先暂停并上报
