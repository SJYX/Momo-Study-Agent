---
date: 2026-05-12
status: draft
scope: 全站统一设计语言规范（Token / 组件 / 布局 / 内容）
related:
  - docs/superpowers/specs/2026-05-11-web-ui-redesign-ops-and-today-design.md
  - docs/dev/web_ui/README.md
---

# Web UI 统一设计语言规范

> 本文档定义 MOMO Agent 全站统一的设计语言，涵盖 Token、组件、布局、内容四个层次。
> 目标：将暖色 Notion 风格从 OpsMonitor/TodayTasks/Sidebar 推广到所有页面。

## 0. 范围与非目标

### 0.1 包含

- **Token 层**：扩展设计 Token（Success/Warning 状态色、Spacing、Typography）
- **组件层**：统一 6 类基础组件（按钮、表单、状态指示、卡片、表格、弹窗）
- **布局层**：统一 Topbar + 可选 Hero 的页面骨架
- **内容层**：统一信息层次、数据展示、空状态、加载状态、响应式

### 0.2 不包含

- 暗色模式
- 动画/微交互系统（本期仅做骨架屏 shimmer）
- 键盘快捷键体系
- Storybook / Playwright 等工具链投资

### 0.3 验收边界

- 所有页面视觉风格统一为暖色 Notion 系
- 组件库完整可用，页面改造完成
- 新 UI 通过 feature flag 保护，可一键回退

---

## 1. Token 层（第一层）

### 1.1 现有 Token（保持不变）

```css
/* Surface（背景层） */
--color-surface-base: #FAF8F3;
--color-surface-card: #FFFFFF;
--color-surface-sidebar: #F4ECDD;
--color-surface-hover: #F1ECE3;
--color-surface-highlight: #FCEFE5;

/* Border */
--color-border-default: #E9E0CD;
--color-border-soft: #F1ECE3;
--color-border-hero: #F4E1D2;

/* Text */
--color-text-primary: #37352F;
--color-text-secondary: #6B5D45;
--color-text-muted: #908A7F;

/* Accent（暖橙） */
--color-accent: #D97757;
--color-accent-hover: #B85433;
--color-accent-soft: rgba(217, 119, 87, 0.15);

/* Error */
--color-error: #B43421;
--color-error-soft: #FDE7E3;

/* Radius */
--radius-pill: 6px;
--radius-button: 8px;
--radius-card: 12px;

/* Shadow */
--shadow-card: 0 1px 3px rgba(15, 15, 15, 0.04);
--shadow-hero: 0 2px 8px rgba(217, 119, 87, 0.08);
```

### 1.2 新增状态色

| Token | 值 | 用途 |
|-------|-----|------|
| `success` | `#2E7D32` | 成功提示、完成状态 |
| `success-soft` | `#E8F5E9` | 成功 pill 背景 |
| `warning` | `#E65100` | 警告提示、需要注意 |
| `warning-soft` | `#FFF3E0` | 警告 pill 背景 |

### 1.3 Spacing Token

基于 4px 基准的间距系统：

```css
--spacing-1: 4px;
--spacing-2: 8px;
--spacing-3: 12px;
--spacing-4: 16px;
--spacing-5: 20px;
--spacing-6: 24px;
--spacing-8: 32px;
--spacing-10: 40px;
--spacing-12: 48px;
```

**使用指南**：
- 组件内间距：`spacing-2` ~ `spacing-4`
- 卡片内间距：`spacing-4` ~ `spacing-5`
- 页面边距：`spacing-6`
- 区块间距：`spacing-6` ~ `spacing-8`

### 1.4 Typography Token

```css
/* 字号 */
--text-xs: 11px;
--text-sm: 12px;
--text-base: 14px;
--text-lg: 18px;
--text-xl: 24px;
--text-2xl: 32px;

/* 字重 */
--font-normal: 400;
--font-medium: 500;
--font-semibold: 600;
--font-bold: 700;

/* 行高 */
--leading-tight: 1.25;
--leading-normal: 1.5;
--leading-relaxed: 1.75;
```

**语义化用法**：
- 页面标题：`text-xl font-bold`
- 区块标题：`text-lg font-semibold`
- 卡片标题：`text-base font-medium`
- 正文：`text-sm font-normal`
- 标签/时间戳：`text-xs font-normal text-muted`
- Hero 大字：`text-2xl font-bold`

---

## 2. 组件层（第二层）

### 2.1 按钮组件

#### 2.1.1 主按钮（Primary）

```html
<button class="bg-accent text-white px-4 py-2 rounded-button text-sm font-medium
               hover:bg-accent-hover transition-colors">
  操作
</button>
```

**使用场景**：页面主 CTA、表单提交

#### 2.1.2 次按钮（Secondary）

```html
<button class="bg-accent-soft text-accent-hover px-4 py-2 rounded-button text-sm font-medium
               hover:bg-accent/20 transition-colors">
  操作
</button>
```

**使用场景**：次要操作、取消

#### 2.1.3 幽灵按钮（Ghost）

```html
<button class="bg-transparent text-text-secondary px-4 py-2 rounded-button text-sm font-medium
               border border-border-default hover:bg-surface-hover transition-colors">
  操作
</button>
```

**使用场景**：筛选切换、低优先级操作

#### 2.1.4 危险按钮（Danger）

```html
<button class="bg-error text-white px-4 py-2 rounded-button text-sm font-medium
               hover:bg-error/90 transition-colors">
  删除
</button>
```

**使用场景**：删除、不可逆操作

#### 2.1.5 按钮尺寸

| 尺寸 | 类名 | 用途 |
|------|------|------|
| Small | `px-3 py-1.5 text-xs` | 表格行内、紧凑空间 |
| Medium（默认） | `px-4 py-2 text-sm` | 通用 |
| Large | `px-6 py-3 text-base` | Hero CTA |

### 2.2 表单组件

#### 2.2.1 输入框

```html
<input class="w-full px-3 py-2 border border-border-default rounded-button text-sm
              bg-surface-card text-text-primary placeholder-text-muted
              focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20" />
```

#### 2.2.2 下拉框

```html
<select class="w-full px-3 py-2 border border-border-default rounded-button text-sm
               bg-surface-card text-text-primary
               focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20">
  <option>选项</option>
</select>
```

#### 2.2.3 文本域

```html
<textarea class="w-full px-3 py-2 border border-border-default rounded-button text-sm
                 bg-surface-card text-text-primary placeholder-text-muted resize-vertical
                 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
          rows="4"></textarea>
```

#### 2.2.4 复选框 / 单选框

```html
<!-- 复选框 -->
<label class="flex items-center gap-2 cursor-pointer">
  <input type="checkbox" class="w-4 h-4 rounded border-border-default text-accent
                                 focus:ring-accent/20" />
  <span class="text-sm text-text-primary">选项</span>
</label>

<!-- 单选框 -->
<label class="flex items-center gap-2 cursor-pointer">
  <input type="radio" class="w-4 h-4 border-border-default text-accent
                              focus:ring-accent/20" />
  <span class="text-sm text-text-primary">选项</span>
</label>
```

### 2.3 状态指示组件

#### 2.3.1 Badge（小徽章）

```html
<span class="inline-flex items-center px-2 py-0.5 rounded-pill text-xs font-medium
             bg-accent-soft text-accent-hover">
  运行中
</span>
```

**状态变体**：
- 默认：`bg-accent-soft text-accent-hover`
- 成功：`bg-success-soft text-success`
- 警告：`bg-warning-soft text-warning`
- 错误：`bg-error-soft text-error`

#### 2.3.2 Pill（胶囊标签）

```html
<span class="inline-flex items-center gap-1 px-3 py-1 rounded-pill text-sm font-medium
             bg-surface-hover text-text-secondary">
  <span class="w-2 h-2 rounded-full bg-accent"></span>
  状态
</span>
```

#### 2.3.3 进度条

```html
<div class="w-full h-2 bg-surface-hover rounded-full overflow-hidden">
  <div class="h-full bg-accent rounded-full transition-all" style="width: 60%"></div>
</div>
```

#### 2.3.4 状态点

```html
<span class="w-2 h-2 rounded-full bg-success"></span>
<span class="w-2 h-2 rounded-full bg-warning"></span>
<span class="w-2 h-2 rounded-full bg-error"></span>
<span class="w-2 h-2 rounded-full bg-accent animate-pulse"></span>
```

### 2.4 卡片组件

#### 2.4.1 标准卡片

```html
<div class="bg-surface-card rounded-card border border-border-default shadow-card p-4">
  <h3 class="text-base font-medium text-text-primary mb-2">卡片标题</h3>
  <p class="text-sm text-text-secondary">卡片内容</p>
</div>
```

#### 2.4.2 Hero 卡片

```html
<div class="bg-gradient-to-br from-surface-highlight to-surface-base
            rounded-card border border-border-hero shadow-hero p-5">
  <h3 class="text-lg font-semibold text-text-primary mb-2">重点内容</h3>
  <p class="text-sm text-text-secondary">详细信息</p>
</div>
```

### 2.5 表格组件

```html
<div class="bg-surface-card rounded-card border border-border-default shadow-card overflow-hidden">
  <table class="w-full">
    <thead>
      <tr class="border-b border-border-soft">
        <th class="px-4 py-3 text-left text-xs font-medium text-text-muted uppercase">列标题</th>
      </tr>
    </thead>
    <tbody>
      <tr class="border-b border-border-soft hover:bg-surface-hover transition-colors">
        <td class="px-4 py-3 text-sm text-text-primary">内容</td>
      </tr>
      <tr class="bg-surface-highlight"> <!-- 高亮行（运行中） -->
        <td class="px-4 py-3 text-sm text-text-primary">高亮内容</td>
      </tr>
    </tbody>
  </table>
</div>
```

### 2.6 弹窗组件

#### 2.6.1 模态框

```html
<div class="fixed inset-0 z-50 flex items-center justify-center">
  <!-- 遮罩 -->
  <div class="absolute inset-0 bg-black/50"></div>
  <!-- 内容 -->
  <div class="relative bg-surface-card rounded-card shadow-lg max-w-md w-full mx-4 p-6">
    <h3 class="text-lg font-semibold text-text-primary mb-4">标题</h3>
    <p class="text-sm text-text-secondary mb-6">内容</p>
    <div class="flex justify-end gap-3">
      <button class="px-4 py-2 rounded-button text-sm border border-border-default
                     text-text-secondary hover:bg-surface-hover">取消</button>
      <button class="px-4 py-2 rounded-button text-sm bg-accent text-white
                     hover:bg-accent-hover">确认</button>
    </div>
  </div>
</div>
```

#### 2.6.2 Popover

```html
<div class="relative">
  <button>触发</button>
  <div class="absolute top-full right-0 mt-2 w-64 bg-surface-card rounded-card
              border border-border-default shadow-lg p-4 z-50">
    Popover 内容
  </div>
</div>
```

---

## 3. 布局层（第三层）

### 3.1 统一 Topbar

```html
<div class="flex h-screen">
  <!-- Sidebar -->
  <aside class="w-56 bg-surface-sidebar border-r border-border-default flex-shrink-0">
    <!-- Sidebar 内容 -->
  </aside>

  <!-- 主内容区 -->
  <div class="flex-1 flex flex-col overflow-hidden">
    <!-- Topbar -->
    <header class="h-14 bg-surface-base border-b border-border-default flex items-center
                    justify-between px-6 flex-shrink-0">
      <div class="flex items-center gap-3">
        <h1 class="text-xl font-bold text-text-primary">页面标题</h1>
        <span class="text-sm text-text-muted">@profile</span>
      </div>
      <div class="flex items-center gap-2">
        <!-- 操作按钮 -->
      </div>
    </header>

    <!-- 内容区 -->
    <main class="flex-1 overflow-auto p-6">
      <!-- 页面内容 -->
    </main>
  </div>
</div>
```

### 3.2 可选 Hero 区

**使用场景**：FuturePlan、WordLibrary 等复杂页面

```html
<main class="flex-1 overflow-auto">
  <!-- Hero 区（可选） -->
  <div class="px-6 pt-6 pb-4">
    <div class="bg-gradient-to-br from-surface-highlight to-surface-base
                rounded-card border border-border-hero shadow-hero p-5">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="text-lg font-semibold text-text-primary">页面概览</h2>
          <p class="text-sm text-text-secondary mt-1">状态说明</p>
        </div>
        <div class="flex items-center gap-3">
          <!-- 统计数据 -->
          <button class="bg-accent text-white px-4 py-2 rounded-button text-sm font-medium">
            主操作
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- 内容区 -->
  <div class="px-6 pb-6">
    <!-- 表格/列表/表单 -->
  </div>
</main>
```

### 3.3 页面骨架模板

#### 模板 A：数据展示页（FuturePlan、WordLibrary）

```
Topbar
└─ Hero 区（概览 + 主操作）
   └─ 筛选/操作栏
      └─ 表格/列表
```

#### 模板 B：状态监控页（OpsMonitor、SyncStatus）

```
Topbar
└─ Hero 区（状态概览 + 主操作）
   └─ 卡片网格（2-3 列）
```

#### 模板 C：任务执行页（TodayTasks）

```
Topbar
└─ Hero 区（四态变形）
   └─ 筛选条
      └─ 任务列表
```

#### 模板 D：配置管理页（Users、Preflight、Gateway）

```
Topbar
└─ 表单区域（单列或双列布局）
```

---

## 4. 内容层（第四层）

### 4.1 信息层次

| 层次 | 样式 | 用途 |
|------|------|------|
| 页面标题 | `text-xl font-bold text-text-primary` | Topbar 标题 |
| 区块标题 | `text-lg font-semibold text-text-primary` | Hero、卡片标题 |
| 卡片标题 | `text-base font-medium text-text-primary` | 卡片内标题 |
| 正文 | `text-sm text-text-secondary` | 描述、说明 |
| 弱文字 | `text-xs text-text-muted` | 标签、时间戳、辅助信息 |

### 4.2 数据展示

#### 大数字统计

```html
<div>
  <span class="text-2xl font-bold text-text-primary">1,234</span>
  <span class="text-sm text-text-muted ml-1">总单词</span>
</div>
```

#### 统计卡片

```html
<div class="bg-surface-card rounded-card border border-border-default shadow-card p-4">
  <div class="text-xs text-text-muted mb-1">运行中</div>
  <div class="text-2xl font-bold text-accent">3</div>
  <div class="text-xs text-text-muted mt-1">+2 较昨日</div>
</div>
```

### 4.3 空状态

```html
<div class="text-center py-12">
  <div class="text-4xl mb-4">🎉</div>
  <h3 class="text-lg font-semibold text-text-primary mb-2">今日已清空</h3>
  <p class="text-sm text-text-secondary mb-6">没有待处理的单词了</p>
  <div class="flex justify-center gap-3">
    <button class="px-4 py-2 rounded-button text-sm border border-border-default
                   text-text-secondary hover:bg-surface-hover">
      看未来计划
    </button>
    <button class="px-4 py-2 rounded-button text-sm bg-accent-soft text-accent-hover
                   hover:bg-accent/20">
      智能迭代
    </button>
  </div>
</div>
```

### 4.4 加载状态

#### 骨架屏

```html
<div class="animate-pulse">
  <div class="h-4 bg-surface-hover rounded w-3/4 mb-4"></div>
  <div class="h-4 bg-surface-hover rounded w-1/2 mb-4"></div>
  <div class="h-4 bg-surface-hover rounded w-5/6"></div>
</div>
```

#### 进度指示

```html
<div class="flex items-center gap-2">
  <svg class="animate-spin h-4 w-4 text-accent" viewBox="0 0 24 24">
    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/>
    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
  </svg>
  <span class="text-sm text-text-secondary">加载中...</span>
</div>
```

### 4.5 响应式断点

```css
/* Tailwind 默认断点 */
sm: 640px
md: 768px
lg: 1024px
xl: 1280px
2xl: 1536px
```

**适配策略**：
- **Sidebar**：< 1024px 折叠为图标模式
- **Topbar**：< 768px 简化操作按钮
- **表格**：< 768px 切换为卡片列表
- **Hero 区**：< 640px 堆叠布局

---

## 5. 实施计划

### 5.1 阶段划分

| 阶段 | 内容 | 周期 | 交付物 |
|------|------|------|--------|
| Phase 1 | Token 层扩展 | 1-2 天 | 更新 `index.css`，新增 Token |
| Phase 2 | 组件层（按钮、表单、状态指示） | 3-4 天 | 组件库 + 文档 |
| Phase 3 | 组件层（卡片、表格、弹窗）+ 布局层 | 3-4 天 | 组件库 + 布局模板 |
| Phase 4 | 内容层 + 页面改造 | 4-5 天 | 所有页面改造完成 |
| Phase 5 | 响应式 + 测试 + 验收 | 2-3 天 | 测试通过 + 用户验收 |

**总计：约 2-3 周**

### 5.2 页面改造优先级

| 优先级 | 页面 | 理由 |
|--------|------|------|
| P0 | FuturePlan、WordLibrary | 高频学习页面 |
| P1 | Iteration | 学习核心 |
| P2 | SyncStatus、Preflight | 系统管理 |
| P3 | Users、Gateway | 低频配置 |

### 5.3 Feature Flag 策略

```typescript
// 新增 flag
ff_unified_tokens    // Token 层扩展
ff_unified_components // 组件层统一
ff_unified_layout    // 布局层统一
ff_unified_content   // 内容层统一
```

**策略**：
- 每个 Phase 独立 flag，默认 `off`
- 验收通过后逐步开启
- 保留旧 UI 代码 1 个版本周期

---

## 6. 风险与回退

| 风险 | 处置 |
|------|------|
| 组件库不够用 | 预留扩展点，按需新增组件 |
| 页面改造回归 | Feature flag 保护，可一键回退 |
| 响应式适配复杂 | 先做桌面端，移动端后续迭代 |
| 性能影响 | 骨架屏优化加载体验 |

---

## 7. 测试 & 验收

### 7.1 自动化测试

- Token 变量正确性测试
- 组件渲染快照测试
- 布局响应式测试

### 7.2 手动验收清单

1. 所有页面视觉风格统一
2. 组件交互正常（hover、focus、active）
3. 空状态、加载状态正确显示
4. 响应式布局在不同断点下正常
5. Feature flag 可正常切换

---

## 附：设计决策溯源

| 决策点 | 选项 | 选定 | 理由 |
|--------|------|------|------|
| 设计风格 | A 深化暖色 / B 极简 / C 看板 / D 混合 | A | 保持一致性，降低学习成本 |
| 统一范围 | 全部页面 / 仅核心组件 / 渐进式 | 全部页面 | 完全统一，不留死角 |
| 实施方法 | 渐进式 / 一次性 / 分层 | 分层 | 结构清晰，便于维护 |
| 布局方案 | 全部Hero / 按需Hero / 统一Topbar+可选Hero | 统一Topbar+可选Hero | 平衡统一性与灵活性 |
| 组件优先级 | 按钮 > 表单 > 状态 > 卡片 > 表格 > 弹窗 | 同左 | 影响范围排序 |
