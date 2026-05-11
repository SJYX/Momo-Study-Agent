---
date: 2026-05-11
status: draft
scope: 前端视觉与局部交互重做（不动后端 / 数据流 / 状态机）
related:
  - docs/dev/web_ui/chapters/C02_TODAY_COMMAND_CENTER.md
  - docs/dev/web_ui/chapters/C05_OPS_MONITOR.md
  - docs/dev/web_ui/chapters/GLOBAL_TODAY_GUARDRAILS.md
---

# Web UI 改版设计 · OpsMonitor + TodayTasks

> 本文档是 brainstorming 结论的固化版本，作为后续 `writing-plans` 的输入。
> 决策过程的可视对照保存在 `.superpowers/brainstorm/1487-1778499752/content/`。

## 0. 范围与非目标

### 0.1 包含

- **重做**：OpsMonitor 监控台、TodayTasks 今日任务、全局 Sidebar 的视觉与布局
- **顺带**：OpsMonitor 顶部控制条收纳简化、OpsMonitor → Today 的 drill-down 上下文传递增强

### 0.2 不包含（明确不做，避免 scope creep）

- 其他页面的视觉调整（Future / Iteration / Words / Sync / Preflight / Users / Gateway）
- 任何后端 API / 数据流 / 状态机 / 进程锁 / 同步逻辑改动
- 暗色模式
- 键盘快捷键体系
- 运行中离开页面提示、轻确认条 "今后不再提示"、智能 done-CTA 等独立执行环优化（本期不做）
- TaskDrawer 组件改造
- 现有特性 flag 体系的删改（V1 features 保持启用，新增 flag 用于本期改版保护）

### 0.3 验收边界

- 视觉风格统一为暖色 Notion / Obsidian 系
- OpsMonitor 改成 Hero + 三卡布局
- TodayTasks 改成 Progress Hero + 列表布局，Hero 在 idle / running / done / empty 四态下变形
- 新 UI 通过 feature flag 保护，可一键回退到老 UI

---

## 1. 视觉基础（Design Tokens）

整套色板、字号、圆角、阴影通过 Tailwind v4 的 `@theme` CSS 变量声明落地；改写的 3 个组件内硬编码颜色全部替换为 token。

### 1.1 色板

| Token | 值 | 用途 |
| --- | --- | --- |
| `surface-base` | `#FAF8F3` | 页面背景（米白） |
| `surface-card` | `#FFFFFF` | 卡片底 |
| `surface-sidebar` | `#F4ECDD` | Sidebar 底 |
| `surface-hover` | `#F1ECE3` | hover 态 |
| `surface-highlight` | `#FCEFE5` | running 行 / hero 渐变末端 |
| `border-default` | `#E9E0CD` | 卡片/sidebar 边框 |
| `border-soft` | `#F1ECE3` | 表格分隔线 |
| `border-hero` | `#F4E1D2` | Hero 边框 |
| `text-primary` | `#37352F` | 主文字（接近黑） |
| `text-secondary` | `#6B5D45` | 次文字（暖灰棕） |
| `text-muted` | `#908A7F` | 弱文字（标签/时间戳） |
| `accent` | `#D97757` | 主强调（CTA / running / active） |
| `accent-hover` | `#B85433` | active 文字 / 主按钮 hover |
| `accent-soft` | `rgba(217,119,87,0.15)` | active 背景 / secondary 按钮 |
| `error` | `#B43421` | 错误 |
| `error-soft` | `#FDE7E3` | 错误 pill 背景 |

### 1.2 状态色策略

**绿色不作为状态色使用**。done 状态靠 ✓ 图标和文案表达，不变底色。
理由：在暖色 Notion 风里冷绿会"打架"；克制色彩可以让重要警告（红）更突出。

唯一例外：`error` 用红色（已是暖色域 #B43421），属语义不可让步。

### 1.3 字号 & 字重

```text
text-xs   11px / 400  — 标签、时间戳
text-sm   12px / 500  — 次要文字、表格行
text-base 14px / 500  — 卡片标题、按钮
text-lg   18px / 700  — Hero 主信息
text-xl   24px / 700  — 页面标题
text-2xl  32px / 700  — Hero 大字（数字/单词）
```

### 1.4 圆角 & 阴影 & 间距

- 卡片圆角 `12px`，pill `6px`，按钮 `8px`
- 卡片阴影：`0 1px 3px rgba(15,15,15,0.04)`（极浅，Notion 风）
- Hero 阴影：`0 2px 8px rgba(217,119,87,0.08)`（极浅暖染色）
- 间距单位 4px；页面 `p-6`、卡片 `p-4`、组件 gap `gap-3`

### 1.5 落地方式

- 项目使用 **Tailwind v4**（CSS-first 配置）。在 `src/index.css` 的 `@theme` 块中声明 CSS 变量，Tailwind 自动生成对应工具类（如 `bg-surface-base` / `text-text-primary`）。
- `@theme` 同时使 CSS 变量在运行时可用（`var(--color-accent)`），用于无法 Tailwind 化的场景（动态颜色、内联 style）。
- 老代码中硬编码的颜色（如 `bg-gray-50`、`bg-blue-600`、`text-red-500`）**仅在本期改写的 3 个组件内**批量替换为新 token；其他页面保持原貌（属于明确不动范围）。

---

## 2. 全局 Chrome · Sidebar

### 2.1 视觉

- 宽度保持 224px
- 底色 `#F4ECDD`，右侧 1px `#E9E0CD` 边
- Logo 区："MOMO Agent" 用 `text-primary` `font-bold`，sublabel "智能单词助记系统" 用 `text-muted`
- nav 项：默认 `text-secondary`，hover `text-primary`，active 背景 `accent-soft` + 文字 `accent-hover` + `font-semibold`
- Footer 行：profile 名 + 切换图标，颜色全部按暖灰

### 2.2 不变

- 9 个 nav 项保持不动
- `useProfileStore` / 切换逻辑保持不动
- prefetch 逻辑保持不动

---

## 3. OpsMonitor 监控台

### 3.1 骨架

```text
┌─────────────────────────────────────────────────────────────┐
│ Topbar: [标题 · @profile]            [⚙ 设置][🔄 刷新][CTA] │
├─────────────────────────────────────────────────────────────┤
│ [告警条：仅在 system 异常时出现，红色，可点击跳详情]         │
├─────────────────────────────────────────────────────────────┤
│ Hero                                                         │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 最近 1 小时                                              │ │
│ │ ✓ 全系统正常 · 3 项待执行                                │ │
│ │ [运行 3] [已完成 42] [错误 1]      [进入今日 →]          │ │
│ └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│ [失败热点]    [系统健康]    [队列与延迟]                     │
│ 三张次级卡，等宽，桌面 grid-cols-3                          │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Hero 内容契约

| 区域 | 内容 | 数据来源 |
| --- | --- | --- |
| 时间窗口 label | "最近 1 小时" / "最近 15 分钟" / "最近 24 小时" | `timeWindow` state |
| 状态徽章 | `system_ok` 为真：✓ 全系统正常；否：⚠️ 系统健康异常 | `data.system_ok` |
| 副信息 | "N 项待执行 · M 项错误" | `tasks_running` + `tasks_error_1h` |
| 三 stat | 运行中 / 已完成 / 错误 | `tasks_running`, `tasks_done_1h`, `tasks_error_1h` |
| 主 CTA | "进入今日 →"，跳 `/today` | navigate |

### 3.3 三张次级卡内容

#### 失败热点

- 默认 5 行，"展开全部" 链接
- 每行：图标 + error_type + count + 时间
- 点击单行：drill-down 跳 `/today?error_type=<encoded>&window=<window>`

#### 系统健康

- 顶部一句话状态 + 检查项列表（默认 5，可展开）
- 异常项靠 `text-error` + `font-medium` 突出，无需变背景色

#### 队列与延迟

- 横排 3 个 stat：同步队列 / 冲突数 / 平均延迟

### 3.4 顶部控制条简化（操作改进）

**当前**：`[时间窗口] [轮询间隔] [刷新] [静音] [CSV 导出] [进入今日]` 全部并排

**改后**：

- 主行只保留 `[🔄 刷新] [进入今日 CTA]`
- 左移一个 `[⚙ 设置]` 弹出 popover，内含：
  - 时间窗口（radio: 15m / 1h / 24h）
  - 轮询间隔（radio: 5s / 10s / 30s）
  - 静音（switch）
  - 导出当前视图（button）

**实现**：

- 新组件 `<OpsSettingsPopover />`，受控 props（值、onChange、当前 data 用于导出）
- 项目当前 **没有** Radix / Headless UI 等 popover 库。自行实现：absolute 定位 div + outside-click 关闭 + Escape 关闭 + portal 到 `document.body`。可后续按需引入 `@radix-ui/react-popover` 替换。
- localStorage 持久化 `timeWindow`、`pollInterval`、`muted`（"静音" 已有，新增另两个）

### 3.5 Drill-down 上下文增强（操作改进）

**当前**：从失败热点跳 Today 只带 `error_type`、`window` 两个 query 参数，Today 页**没有读取并应用筛选**。

**改后**：

- OpsMonitor 跳转保留现状（`?error_type=&window=`）
- Today 页解析 URL 参数，初始化 `filterErrorType` / `filterWindow` 两个 state
- 列表顶部出现"已应用筛选：xxx 错误 · 最近 1 小时 ✕"提示条，点 ✕ 清除筛选回到全部
- 当前 V1 的 `showAll` / 价值优先逻辑保留，叠加在 URL 筛选之上

---

## 4. TodayTasks 今日任务

### 4.1 骨架

```text
┌─────────────────────────────────────────────────────────────┐
│ Topbar: [今日任务 · N 个单词 · 更新于 xx:xx]    [🔄 强制刷新]│
├─────────────────────────────────────────────────────────────┤
│ Hero（四态变形，下面详述）                                   │
├─────────────────────────────────────────────────────────────┤
│ [筛选条：仅可执行 ⇄ 全部 (N) · 价值优先]  [暂停跟随（运行中）]│
├─────────────────────────────────────────────────────────────┤
│ 列表：紧凑表格                                               │
│  # | 单词 | 状态 pill + phase                              │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Hero 四态契约

**判定优先级**：`isTaskRunning` → `isTerminal` → `items.length === 0` → 默认 idle

#### ① Idle（默认）

- 顶部 label "今日待处理 · 价值优先"
- 主文 `<text-2xl font-bold>N 个单词</text-2xl>`
- 副信息 "M 可执行 · K 已完成"
- 两按钮：
  - 主：`▶ 全部处理`（暖橙）→ 触发 `handleClick`
  - 次：`仅可执行 ⇄ 全部` 切换（轻按钮）→ 触发 `setShowAll`
- 数据为空 N=0 → 进入 ④ Empty

#### ② Running

- 顶部行：左 "正在处理 (k/N)"，右 "⏱ 已耗时 12s"（client tick）
- 主文：当前 running 行的 `voc_spelling`（大字号）
- phase 行：`⚡ 生成 AI 释义中 · 阶段 3/5`（取 `rowStatusMap[current].phase`）
- 进度条：基于 `(statusCounts.done + statusCounts.error + statusCounts.skipped) / items.length`
- 4 stat 横排：完成 / 运行 / 错误 / 待
- 主 CTA：`⏹ 停止处理`（红 `error` 色）→ `handleCancel`

#### ③ Done（terminal）

- 顶部 label "✓ 处理完成 · 耗时 1m 24s"（terminal 时刻 - 开始时刻）
- 主文：`5 成功 · 1 失败 · 1 跳过`
- 副信息：成功率 % · AI 调用次数 · 同步队列变化（如果易得；否则只显示成功率）
- 按钮：
  - 主：`查看失败 (N) →`（红色）→ `setShowFailureMode(true)`（仅在 `error > 0`）
  - 次：`再来一批`（暖橙轻按钮）→ `c.refresh()` 或 `c.handleClick()`
- **不变色**（决策 Z）：背景仍是 idle 的米白渐变 + 暖橙边，靠 ✓ 图标 + "处理完成" 文案传达

#### ④ Empty

- 当 `data?.count === 0` 且非 terminal
- 28px 🎉 + "今日已清空" + 副"没有待处理的单词了"
- 两个轻按钮：`看未来计划 →`、`智能迭代 →`
- 虚线边框替代实线，弱化"卡片"感

### 4.3 列表

- 紧凑表格（保留当前结构）
- pill 状态色使用新 token（暖色），状态文案保留
- 当前 running 行整行高亮 `bg-surface-highlight`
- 错误行 reason 用 `text-error`，warning 用暖橙
- `displayItems` / `sortedItems` / `executableItems` 计算保留（来自 `useTodayController`）

### 4.4 筛选条 + 提示

- 当 `showAll === false`：显示 "仅可执行 (M)"
- 当 `showAll === true`：显示 "查看全部 (N)"
- running 期间额外提示：`筛选仅影响显示，不影响正在执行的任务`
- `followPaused` 切换按钮保留位置（最右侧）
- **当从 OpsMonitor 带筛选进来**：列表上方出现独立提示条 `"已应用筛选：xxx 错误 · 1h ✕"`，点 ✕ 清除

---

## 5. 组件 & 文件结构

### 5.1 新增

```text
web/frontend/src/
├── styles/
│   └── tokens.css                 # 全局 CSS 变量（如不放 index.css 时）
├── components/
│   ├── layout/
│   │   └── Sidebar.tsx            # 改写
│   ├── ops/
│   │   ├── OpsHero.tsx            # 新
│   │   ├── OpsSettingsPopover.tsx # 新
│   │   ├── FailureHotspotsCard.tsx# 抽出
│   │   ├── SystemHealthCard.tsx   # 抽出
│   │   └── QueueLatencyCard.tsx   # 抽出
│   └── today/
│       ├── TodayHero.tsx          # 新（含 4 态分发）
│       ├── TodayHeroIdle.tsx      # 新
│       ├── TodayHeroRunning.tsx   # 新
│       ├── TodayHeroDone.tsx      # 新
│       ├── TodayHeroEmpty.tsx     # 新
│       └── DrillDownNotice.tsx    # 新（URL 筛选提示条）
```

### 5.2 改写

- `pages/OpsMonitor.tsx` — 重写渲染层，逻辑（query / useOnActiveUserChanged）保留
- `pages/TodayTasks.tsx` — 重写渲染层，`useTodayController` 接口保留
- `components/layout/Sidebar.tsx` — 重写样式
- `src/index.css` — 在 `@theme` 块内声明新 token（Tailwind v4 CSS-first 配置）

### 5.3 不动

- `hooks/useTodayController.ts`
- `api/`、`queries/`、`stores/`
- `components/tasks/TaskDrawer.tsx`
- `components/today/LightConfirmBar.tsx` / `SummaryPanel.tsx` / `FailureGroupsPanel.tsx` / `BulkGuardModal.tsx`
  - **注**：SummaryPanel 的角色被新 TodayHeroDone 替代；旧组件保留代码但停止挂载，下个周期再清理

---

## 6. 状态机 & 数据契约

本期**不改任何状态机**。所有变化在渲染层：

- OpsMonitor 的 `useQuery` / refetchInterval / queryKey 保持
- Today 的 `useTodayController` 返回结构保持（`isTaskRunning` / `isTerminal` / `statusCounts` / `rowStatusMap` / `executableItems` 等）
- 新 Hero 在 ② running 中需要 "已耗时"：本地 `useEffect` + setInterval（不入 controller，纯渲染装饰）

URL 参数契约（drill-down）：

```text
/today?error_type=<encoded>&window=<15m|1h|24h>
```

Today 页解析后写入本地 state，不调用任何 mutation 也不触发刷新（数据已经在内存）；只影响 `displayItems` 的过滤逻辑（叠加在现有 `showAll` 之上）。

---

## 7. 实施步骤（给 writing-plans 的参考）

按 5 个批次推进，每个批次单独合入：

1. **Step 1 · Tokens**：在 `src/index.css` 的 `@theme` 内声明新色板/字号/圆角/阴影变量。**不需要 flag** —— 仅添加 token 不会影响任何现有组件（它们引用的还是旧 class）。
2. **Step 2 · Sidebar**：换皮，nav 项交互保持。
3. **Step 3 · OpsMonitor**：Hero + 三卡 + 顶部控制条收纳到 popover。
4. **Step 4 · TodayTasks**：Progress Hero 四态 + 列表样式 + DrillDownNotice。
5. **Step 5 · Drill-down 联动**：OpsMonitor → Today 的 URL 参数读取与应用。

Step 2–5 各挂一个 feature flag 保护：

- `ff_redesign_sidebar`
- `ff_redesign_ops`
- `ff_redesign_today`
- `ff_drilldown_v2`

合入主分支默认 `off`，验收完成后由用户在 `data/profiles/<user>.env` 或全局配置开。

---

## 8. 风险与回退

| 风险 | 处置 |
| --- | --- |
| Sidebar 浅色化让 active 项不够醒目 | 三重区分：背景 `accent-soft` + 文字 `accent-hover` + `font-semibold`；线下 review 后必要时加左侧 2px 暖橙条 |
| Hero 占位让列表可视行数减少（尤其 1080p 笔记本） | 移动 Hero 高度控制在 ~140px；列表区 viewport 高度自适应 |
| 顶部控制条收纳后 "切换轮询间隔" 多一次点击 | 用户共识：操作低频；如果反弹严重，下个周期把"轮询间隔"挪回主行 |
| 状态机不变但渲染重写带来 regression | 全部新组件背后挂 feature flag；冒烟 E2E 覆盖 Today 四态、OpsMonitor 健康/异常 |
| URL 筛选与 V1 "仅可执行" 默认冲突 | URL 参数优先级最高；未带 URL 参数时 `showAll` 默认值不变 |

---

## 9. 测试 & 验收

### 9.1 自动化

- 单元测试：新 Hero 组件 4 态渲染快照、URL 解析逻辑
- E2E（不依赖具体颜色，依赖结构与文案）：
  - OpsMonitor 默认进入显示 Hero + 3 卡
  - OpsMonitor 异常态显示告警条 + Hero 副信息变化
  - OpsMonitor → 失败热点点击 → Today 出现 DrillDownNotice
  - Today idle 大 CTA "全部处理" 可点
  - Today running 期间 Hero 显示当前 word + phase
  - Today done 显示"查看失败 (N)"
  - Today 空显示"今日已清空"

### 9.2 手动验收清单

1. 切换 profile 时新 Sidebar 状态恢复正确
2. 各 feature flag 关闭时回退到旧 UI 无 regression
3. 4 种 Today Hero 状态在不同数据量下不挤压
4. 顶部 popover 在窄屏（1280px）下不溢出
5. 错误状态色（红）依然醒目；done 状态在视觉上和 idle 可区分（靠 ✓ + 文案）

---

## 10. 待 writing-plans 决定的细节（不在 spec 范围）

- 5 个 feature flag 的具体命名 & 注册顺序
- 文件移动 / 抽取的具体 patch 拆分
- 是否需要 Storybook / Playwright snapshot diff 工具链投资
- 设计 token 的命名风格（CSS 变量 `--surface-base` vs Tailwind class `bg-surface-base`），建议两者都有

---

## 附：决策溯源

| 决策点 | 选项 | 选定 | 理由 |
| --- | --- | --- | --- |
| 视觉风格 | A 极简 / B 暖调 / C 数据看板 | B | 长时间使用不累，符合学习场景 |
| 改动规模 | 换皮 / 调主次 / 重布局 | 重布局 | 想要明显观感提升 |
| OpsMonitor 骨架 | A Hero+三卡 / B 单栏 / C 双栏 | A | 一眼看清现状 + 主 CTA 明确 |
| TodayTasks 骨架 | α 表格 / β 画廊 / γ Hero+列表 | γ | 与 OpsMonitor A 同源 + 跑起来焦点明确 |
| Sidebar | I 深色 / II 浅色 / III 顶部 | II | 整体风格统一 |
| Done 状态色 | X 鼠尾草 / Y 暖金 / Z 不变色 | Z | 克制；色彩留给主强调和错误 |
| 操作改进范围 | 收纳控制 / 快捷键 / drill-down / 执行环 | 收纳控制 + drill-down | 视觉相关；其他延后 |
