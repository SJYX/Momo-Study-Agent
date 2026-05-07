# V2 任务单（C04 TaskDrawer Smart Icon + C05 Ops Monitor）

版本：v1 初稿
更新时间：2026-05-06
模式：逐任务实现 + 验收

---

## 全局约束

- 所有新交互 behind V2 feature flag
- Kill switch：`?ff_off=v2` 或 `localStorage ff_off=v2`
- 门禁：后端 pytest + 前端 vitest + build + typecheck
- 不破坏 Today 主路径

---

## 任务列表

### T0：V2 Feature Flag 骨架 + 后端 Schema 扩展

**Feature Flags**：

| Flag | 默认 | killable | 关联任务 |
|------|------|----------|----------|
| `ff_taskdrawer_smart_icon` | `true` | true | T2 |
| `ff_taskdrawer_auto_open` | `true` | true | T3 |
| `ff_ops_monitor` | `false` | true | T4 |
| `ff_ops_monitor_polling` | `true` | true | T5 |
| `ff_ops_monitor_alert_bar` | `true` | true | T6 |
| `ff_ops_monitor_csv_export` | `true` | true | T7 |

Kill switch：`ff_off=v2` 关闭所有 `killable=true` 的 V2 flag。

**后端变更**：

1. `web/backend/tasks.py`：
   - `TaskRecord` 新增 `task_type: str = "today"` 和 `profile: str = ""` 字段
   - `TaskRecord.to_dict()` 输出新字段
   - 新增 `TaskRegistry.list_all() -> list[dict]` 方法

2. `web/backend/schemas.py`：
   - 新增 `TaskListItem` Pydantic model
   - 新增 `TaskListResponse` Pydantic model

3. `web/frontend/src/utils/featureFlags.ts`：
   - 新增 `V2_FLAGS` 注册表
   - `evaluateFlag` / `isEnabled` / `snapshotFlags` 支持 V2
   - kill switch 支持 `ff_off=v2`

4. `web/frontend/src/api/types.ts`：
   - 新增 `TaskListItem`、`TaskListResponse` 类型

**验收**：
- [x] V2_FLAGS 注册表存在
- [x] `?ff_off=v2` 关闭所有 V2 flag
- [x] TaskRecord 包含 task_type/profile 字段
- [x] TaskRegistry.list_all() 可用
- [x] 前端 build + test 通过

---

### T1：后端 API — 任务列表 + Ops 聚合

**新增端点**：

1. `GET /api/tasks`（`web/backend/routers/tasks.py`）：
   - Query params：`profile`（必须）、`status`（可选）、`since`（可选，epoch）
   - 返回 `TaskListResponse`
   - 调用 `task_registry.list_all()` + 过滤

2. `GET /api/stats/ops`（`web/backend/routers/stats.py`）：
   - Query params：`profile`（必须）、`window`（可选，默认 `1h`，支持 `15m`/`1h`/`24h`）
   - 返回 `OpsStatsResponse`：
     - `tasks_running`、`tasks_done_1h`、`tasks_error_1h`、`recent_tasks[]`
     - `failure_hotspots[]`（error_type 分组，top 5）
     - `system_ok`、`health_checks[]`
     - `sync_queue_depth`、`sync_conflict_count`、`avg_latency_ms`

3. `web/backend/schemas.py`：
   - 新增 `FailureHotspot`、`OpsStatsResponse` Pydantic model

4. `web/backend/study.py`：
   - `_submit_with_profile_lock()` 传入 `task_type` 参数

**验收**：
- [x] `GET /api/tasks?profile=xxx` 返回任务列表
- [x] `GET /api/stats/ops?profile=xxx&window=1h` 返回四卡片数据
- [x] 新任务记录了 task_type
- [x] 后端 pytest 通过

**依赖**：T0

---

### T2：TaskDrawer Smart Icon 模式

**三种视觉状态**：

1. **Icon**（默认态）：右下角 48x48 圆形图标，状态色 dot + 计数 badge
2. **Minimized**：小型横条按钮（V1 已有）
3. **Expanded**：480px 面板（V1 已有）

**改动文件**：
- `web/frontend/src/stores/tasks.ts` — 新增 `iconMode: boolean`
- `web/frontend/src/components/tasks/TaskDrawer.tsx` — 新增 Icon 渲染分支

**验收**：
- [x] smart icon=on 时，任务触发后右下角出现圆形图标
- [x] 点击图标展开 Drawer
- [x] smart icon=off 时行为与 V1 一致
- [x] 运行中图标有 pulse 动效
- [x] 无任务时不渲染

**依赖**：T0

---

### T3：TaskDrawer 自动展开 + 自动收起

**自动展开**：
- 监听 `row_status` 事件，高风险错误时自动从 Icon 切换到 Expanded
- 高风险：`error_type` 为 `"ai_batch_error"` 或 `"critical"`

**自动收起**：
- 终态 3 秒后自动收起为 Icon
- 用户手动操作取消自动收起

**改动文件**：
- `web/frontend/src/components/tasks/TaskDrawer.tsx`

**验收**：
- [x] 高风险错误自动展开
- [x] 终态 3 秒自动收起
- [x] 用户操作取消自动收起
- [x] auto_open=off 时不触发

**依赖**：T2

---

### T4：Ops Monitor 页面骨架 + 路由切换

**改动文件**：
- `web/frontend/src/pages/OpsMonitor.tsx`（新增）
- `web/frontend/src/router.tsx` — `/` 按 flag 指向 OpsMonitor 或 Dashboard
- `web/frontend/src/components/layout/Sidebar.tsx` — 导航更新

**页面结构**：
- 顶部栏：标题 + Profile + 刷新按钮 + 轮询间隔 + 静音切换 + CTA 按钮
- 主体：2x2 卡片网格（占位）
- 空态/错误态

**验收**：
- [x] flag=on 时 `/` 显示 OpsMonitor
- [x] flag=off 时 `/` 显示原 Dashboard
- [x] Sidebar 导航正确
- [x] build + typecheck 通过

**依赖**：T0

---

### T5：Ops Monitor — 任务态势卡片 + 轮询

**新增文件**：
- `web/frontend/src/hooks/useOpsPolling.ts`

**改动文件**：
- `web/frontend/src/pages/OpsMonitor.tsx` — 卡片1

**卡片1 内容**：
- 运行中/完成/错误计数
- 最近 5 条任务列表（task_type + 状态 + 时间）
- 点击跳转对应页面

**轮询 hook**：
- 支持 5s/10s/30s 切换
- 页面不可见暂停
- 手动刷新

**验收**：
- [x] 计数和任务列表正确
- [x] 轮询可切换
- [x] 页面不可见暂停
- [x] polling=off 不轮询

**依赖**：T1, T4

---

### T6：Ops Monitor — 失败热点 + 系统健康 + 告警条

**新增文件**：
- `web/frontend/src/components/ops/AlertBar.tsx`

**改动文件**：
- `web/frontend/src/pages/OpsMonitor.tsx` — 卡片2、卡片3、告警条

**卡片2**：按 error_type 分组 top 5，点击跳转 Today + 筛选参数
**卡片3**：health_checks 列表，最多 5 行
**告警条**：system_ok=false 时红色条，点击跳转详情

**验收**：
- [x] 失败热点分组正确
- [x] 点击跳转 Today 携带参数
- [x] 健康检查显示正确
- [x] 异常时红色告警条出现

**依赖**：T5

---

### T7：Ops Monitor — 队列卡片 + 时间窗口 + CSV + 静音

**新增文件**：
- `web/frontend/src/utils/opsCsv.ts`

**改动文件**：
- `web/frontend/src/pages/OpsMonitor.tsx` — 卡片4、时间窗口、导出、静音

**卡片4**：sync_queue_depth / avg_latency_ms / conflict_count
**时间窗口**：15m/1h/24h 切换 + URL 参数同步
**CSV 导出**：当前视图数据导出
**静音模式**：仅保留告警条

**验收**：
- [x] 队列数据正确
- [x] 时间窗口切换刷新数据
- [x] CSV 导出可用
- [x] 静音模式生效

**依赖**：T6

---

### T8：验收 + 文档 + 回归

**新增文件**：
- `web/frontend/src/utils/__tests__/opsCsv.test.ts`

**改动文件**：
- `web/frontend/src/utils/__tests__/featureFlags.test.ts` — V2 flag 测试
- `docs/dev/web_ui/CHANGELOG.md`

**门禁**：
1. 后端 pytest：`python -m pytest tests/web/ -v -m "not slow"`
2. 前端 Vitest：覆盖 opsCsv.ts、featureFlags.ts
3. 前端 build：`npm --prefix web/frontend run build`
4. 手动冒烟：Today 主路径 + TaskDrawer icon + Ops Monitor 四卡片

**回退验证**：
- `?ff_off=v2` 关闭所有 V2 功能
- `/` 回退 Dashboard
- TaskDrawer 回退 V1 模式

**依赖**：T3, T7
