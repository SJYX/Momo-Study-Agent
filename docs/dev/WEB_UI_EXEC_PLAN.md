# MoMo Web UI 改造执行计划（最终版）

## 0. 一句话定位
将 MoMo Script 从 CLI 工具升级为本地 Web 控制台：第一阶段不做登录/鉴权，但支持本地多 profile、profile 间并发、同 profile 重任务互斥；Web 成为主入口，CLI 保留备用。

## 1. 背景
当前核心流程可在 CLI 完成，但长任务进度依赖日志、交互效率低、状态可视化不足。目标是将日常流程迁移到 Web，同时保持 core/database/CLI 兼容。

## 2. 第一阶段边界
### 2.1 第一阶段不做（但必须预留扩展位）
- 登录、鉴权、JWT、权限系统
- 云端多租户、公网访问安全、跨设备强一致
- 多设备实时同步、管理员后台

### 2.2 第一阶段必做
- 打开 Web 后先选择或新建 profile
- 前端保存 active profile，并在每个 API 请求携带 `X-Momo-Profile`
- 后端按请求级 profile 加载隔离上下文
- profile 级隔离：配置、数据库、任务、SSE
- 不同 profile 可并发；同 profile 重任务互斥
- Web 覆盖日常主流程；CLI 作为 fallback

### 2.3 扩展预留原则（防止未来大改）
1. 请求上下文统一入口：所有路由必须经 `RequestContext`/`UserContext` 解析，不在业务路由内散落读取 header。
2. Header 预留：当前使用 `X-Momo-Profile`，预留 `Authorization`、`X-Momo-Tenant` 注入位。
3. 依赖注入预留：`deps.py` 保持可插拔 `auth_resolver`、`tenant_resolver`、`device_resolver`。
4. Task 归属键预留：内部统一使用 `scope_id + task_id`，当前 `scope_id=profile`，未来可升级为 `tenant/profile`。
5. 数据模型预留：任务、事件、审计记录保留 `owner_scope` 字段，默认写 profile。
6. Session 结构预留：`/api/session` 的 `data` 预留 `auth_mode`、`tenant_mode`、`consistency_mode`。
7. Host 策略预留：第一阶段默认 `127.0.0.1`，但配置结构支持后续安全模式切换。

## 3. 关键定版决策（本次确认）
1. `POST /api/users` 最小字段：仅 `profile_name` 必填；其余配置（token/provider 等）进入 `ProfileSettings` 或后续补录。
2. 同 profile 重任务冲突策略：第一阶段采用“拒绝并提示”（HTTP 409 + 明确 message），不做排队。
3. `GET /api/session` 返回：统一 `{ok,data,error}`；`data` 必含 `active_profile`、`available_profiles`、`server_time`、`host_binding`。
4. profile 切换行为：前端必须自动取消旧 profile 的 SSE 订阅，并清空 TaskDrawer 当前态，避免串台视觉残留。
5. UI 设计流程：Stitch MCP 作为默认设计入口，先出页面/组件稿，再实现代码。

## 4. 核心架构原则
1. 不做登录，但必须做 profile context
2. 从“启动时锁定单用户”改为“请求级 profile 上下文”
3. 新增 `UserContextManager` 统一管理 profile 隔离对象
4. 锁机制两层：`web-server.lock` + `profile-{name}.lock`
5. `TaskRegistry` 按 profile 隔离（`profile + task_id`）
6. SSE 必须绑定 `profile + task_id`
7. Web 新代码不直接依赖 `config.py` 全局用户态
8. 第一阶段默认仅绑定 `127.0.0.1`
9. 新增模块时必须先检查“是否可注入 auth/tenant/device 解析器”

## 5. 页面范围
- UserGateway
- Dashboard
- Today Tasks
- Future Plan
- Iteration
- Word Library
- Sync Status
- Preflight
- Profile Settings
- Global Task Drawer
- App Shell / Sidebar

## 6. Stitch MCP 执行规范
1. 每个页面改造前先产出 Stitch 草稿（布局、状态、关键交互）。
2. 先改 token/组件，再落具体页面，避免页面各写各的。
3. TaskDrawer、UserGateway、Today/Future/Iteration 为 Stitch 优先级最高页面。
4. 每个阶段结束保留一份 Stitch 产物链接或截图记录到 `docs/dev`。

## 6.1 行级进度通用规范（新增）
1. 所有“列表型任务场景”统一支持行级进度展示，不限于 Today Tasks。
2. 行级状态最小集合：`待处理`、`处理中`、`已完成`、`失败`。
3. 行级进度形态：状态标签 + 细进度条（可选）+ 失败原因提示。
4. 总进度与行级进度必须一致，避免“总进度完成但行状态未完成”。
5. 先在 Today/Future/Iteration 落地，后续扩展到 Word/Sync 等批处理列表。

实现建议（分层落地）：
1. V1：离散状态版（每行只返回 status + error）。
2. V2：阶段版（每行增加 phase）。
3. V3：百分比版（每行增加 current/total 或 percent）。
## 7. 分阶段执行计划
### P0 用户入口 + Profile 上下文基础
- 前端：UserGateway、activeProfile 持久化、路由守卫、显示/切换 profile
- 前端：切换 profile 时自动断开旧 SSE 并重置 TaskDrawer
- 后端：`GET /api/users`、`POST /api/users`、`GET /api/session`、UserContextManager 基础
- 后端：补齐 `RequestContext` 注入点（为 auth/tenant 扩展预留）
- 验收：首次进入网关、选择后入 Dashboard、刷新保留、未选拦截、session 按 profile 返回

### P1 Profile 隔离与并发基础
- 完成 profile 级 context 对象隔离：env/db/client/workflow/task registry/lock
- 引入 server lock 与 profile lock
- 任务与 SSE 按 `profile + task_id`
- 同 profile 重任务冲突返回 409（拒绝并提示）
- 验收：A/B profile 可并发，同 profile 重任务被拒绝且提示明确

### P2 后端核心 API 打通
- 打通 session/users/preflight/study/words/sync/stats/tasks 全部 API
- 统一响应结构 `{ok,data,error}`
- 验收：核心查询与任务触发真实可用，SSE 可消费

### P3 Web 主流程端到端
- Today/Future/Iteration 全流程闭环（触发、进度、结果刷新、错误定位）
- 在 Today/Future/Iteration 列表中统一新增“行级进度列”（状态/阶段/失败提示）
- 验收：三条核心流程不依赖 CLI 可完成，且可按行追踪进度与失败项

### P4 TaskDrawer + 结构化进度
- 用结构化事件替代日志主展示（phase/status/current/total/message）
- 新增行级事件映射（item_id/status/phase/error/current/total）供各列表复用
- 日志改为可折叠调试区
- 验收：不看日志也能判断进度和失败原因，总进度与行级进度一致

### P5 二级能力补齐
- Word Library（分页/筛选/详情/迭代历史）
- Sync Status（队列/失败/冲突/flush）
- Preflight（一键体检 + fix hint）
- 验收：日常排查不依赖 CLI

### P6 视觉统一与体验打磨
- 轻量现代风 token、组件统一、状态统一、窄屏适配
- 验收：全站风格一致、路径清晰、长期可用

### P7 CLI 降级为备用入口
- 保留 `python main.py`，与 Web 共享锁语义
- CLI 检测冲突并给出明确提示
- 验收：Web 主用，CLI 可应急且不破坏数据

### P8 远期（暂不实施）
- 登录/鉴权/JWT/云多租户/公网/跨设备强一致

## 8. 测试与质量门禁
- 后端：`python -m pytest tests/ -v --tb=short -m "not slow"`
- 前端：`npm run build`、`npm run typecheck`（如有 lint 再加）
- 必测：profile 隔离、同 profile 互斥、任务生命周期、SSE 隔离、Web/CLI 冲突、core/database/CLI 回归

## 9. 风险与应对
- 全局状态串用户：Web 统一走 UserContext
- 同 profile 并发写冲突：profile lock + 重任务互斥
- SSE 串台：必须 `profile + task_id`
- 无鉴权安全边界：第一阶段仅绑定 `127.0.0.1`
- 先美化后架构：固定优先级为隔离->主流程->进度->二级功能->视觉
- 扩展返工风险：通过 RequestContext/DI/scope_id 预留降低未来重构成本

## 10. 执行优先级（固定）
`P0 -> P1 -> P2 -> P3 -> P4 -> P5 -> P6 -> P7 -> P8`

## 11. 第一阶段最小可交付（MVP）
- UserGateway
- UserContextManager
- `X-Momo-Profile` header
- profile 级 task lock
- profile 级 TaskRegistry
- Today Tasks
- TaskDrawer
- SSE progress
- 基本 Dashboard

## 12. 当前状态
- 当前阶段：`P1`
- 当前焦点：`Profile 隔离与并发基础`
- 当前原则：`先不串用户/不写坏数据/不串任务，再做视觉美化`
- P0 已完成：UserGateway 向导、profile store、路由守卫、X-Momo-Profile header、session/users API 改造、SSE 重置

