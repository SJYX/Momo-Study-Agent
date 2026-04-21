# MOMO Script — Web 前端界面方案

## 1. Context

本项目 `Momo Study Agent` 当前是终端 CLI 工具：`main.py` 加载单用户配置 → 主菜单 4 项（今日任务 / 未来计划 / 智能迭代 / 退出）→ 背后由 `core/study_workflow.py` 驱动 AI 生成 + 墨墨同步 + 后台队列。

**做这件事的理由：**
- 终端交互不直观：AI 批量进度、同步冲突、薄弱词列表需要表格/图形呈现，CLI 局限大。
- 未来可能远程访问（手机 / 其他机器）。
- 现有单词库/迭代历史已有丰富数据（`ai_word_notes`、`word_progress_history`、`ai_word_iterations`），适合做仪表盘。

**预期结果：**
- 一个 React + TypeScript SPA + FastAPI 后端，复用现有 `core/*` 和 `database/*`，CLI 不拆。
- 第一期：单用户锁定（与当前 `ACTIVE_USER` 兼容）、本地 localhost 运行、Web 为主入口。
- 远期可演进为多租户云服务（设计已预留钩子）。

---

## 2. 用户已决策的关键选项

| 议题 | 选择 |
| --- | --- |
| 部署形态 | 短期本地单人，远期云端多用户 |
| CLI 存废 | 保留，但与 Web 不并发（共享 `process.lock`）|
| 前端栈 | React + Vite + TypeScript |
| 实时通道 | **SSE（Server-Sent Events）** — 推荐 |
| 启动方式 | **独立入口** `python -m web.backend`，与 `python main.py` 并列 |
| 多用户支持 | 第一期单用户锁定；多租户留到 Phase 6 |

---

## 3. 架构全景

```
浏览器 (React SPA)
   │  REST  (/api/*)                      SSE  (/api/tasks/{id}/events)
   ▼                                         ▼
┌─────────────────────────────────────────────────────┐
│ FastAPI ASGI  (uvicorn, workers=1 — 进程锁限制)      │
│ ┌──────────┐  ┌──────────┐  ┌─────────────────────┐ │
│ │ routers/ │  │ deps.py  │  │ TaskRegistry + 事件 │ │
│ │  study   │  │ user_ctx │  │ queue  (SSE 源)     │ │
│ │  words   │  │ logger   │  └─────────┬───────────┘ │
│ │  sync    │  │ lock     │            │             │
│ │  users   │  └──────────┘            │             │
│ │  prefl.  │                          │             │
│ └────┬─────┘                          │             │
│      │   Web → 业务层适配              │             │
│      ▼                                │             │
│  adapters/web_ui_manager.py  ◀────────┘             │
│  adapters/progress_logger.py (tee 日志到 SSE)        │
└──────┬──────────────────────────────────────────────┘
       │ 原生调用（不改动）
       ▼
┌─────────────────────────────────────────────────────┐
│ 现有 core/ + database/                               │
│  StudyWorkflow / IterationManager / SyncManager     │
│  MaiMemoAPI / Gemini|MimoClient                     │
│  database.connection (单写线程 + 云同步线程)          │
│  SQLite + Turso Embedded Replicas                   │
└─────────────────────────────────────────────────────┘
```

**核心不变量（继承 AI_CONTEXT.md MUST 条款）：**

- `core/*`、`database/*` **不改签名、不改语义**，全部以适配方式接入。
- 进程锁 `acquire_process_lock()` 必须由 Web 后端启动时获取（与 CLI 互斥）。
- `BATCH_SIZE`、`AI_PIPELINE_WORKERS`、写队列等并发配置不变。
- 敏感凭据仍只写入 `data/profiles/<user>.env`；Web 层只读/转发，不在前端落地。
- 日志走现有 `core/logger.py`，Web 通过日志 tee 获取事件流，不新建日志通道。

---

## 4. 项目目录增量

```
MOMO_Script/
├── main.py                      # CLI 入口（不动）
├── config.py                    # 不动；Phase 6 再做请求级重构
├── core/                        # 不动
├── database/                    # 不动
├── web/                         # ⬅ 新增
│   ├── __init__.py
│   ├── backend/
│   │   ├── __init__.py
│   │   ├── __main__.py          # python -m web.backend 入口：取锁 → uvicorn
│   │   ├── app.py               # FastAPI 工厂（lifespan: init_concurrent_system / init_db / shutdown）
│   │   ├── deps.py              # 依赖注入：active_user / workflow / momo_api / logger / task_registry
│   │   ├── lock.py              # 抽出 main.py 里的 acquire_process_lock 作共享模块
│   │   ├── tasks.py             # TaskRegistry（UUID → 队列/状态/结果）
│   │   ├── logger_bridge.py     # LoggerAdapter：info/warn/error → task 事件队列
│   │   ├── schemas.py           # Pydantic 请求/响应模型
│   │   ├── routers/
│   │   │   ├── session.py       # GET /api/session（当前锁定用户信息）
│   │   │   ├── study.py         # today / future / process / iterate
│   │   │   ├── words.py         # list / detail / edit note
│   │   │   ├── sync.py          # queue 深度 / 冲突列表 / manual flush
│   │   │   ├── users.py         # list / create (wizard 的 API 版) / delete local
│   │   │   ├── preflight.py     # run_preflight（复用 core/preflight.py）
│   │   │   ├── stats.py         # 聚合统计
│   │   │   └── tasks.py         # GET /{id}  GET /{id}/events (SSE)  POST /{id}/cancel
│   │   └── adapters/
│   │       └── web_ui_manager.py  # 兼容 CLIUIManager 接口；ask_* 改为 HTTP 来回合
│   └── frontend/
│       ├── package.json
│       ├── vite.config.ts        # dev 代理 /api → http://127.0.0.1:8765
│       ├── tsconfig.json
│       ├── index.html
│       ├── src/
│       │   ├── main.tsx
│       │   ├── App.tsx
│       │   ├── router.tsx
│       │   ├── api/
│       │   │   ├── client.ts    # fetch 包装
│       │   │   ├── sse.ts       # EventSource Hook
│       │   │   └── types.ts     # 与 schemas.py 对齐（可用 openapi-typescript 生成）
│       │   ├── components/
│       │   │   ├── layout/Sidebar.tsx
│       │   │   ├── tasks/TaskDrawer.tsx   # 全局悬浮任务面板
│       │   │   └── ...
│       │   ├── pages/
│       │   │   ├── Dashboard.tsx
│       │   │   ├── TodayTasks.tsx
│       │   │   ├── FuturePlan.tsx
│       │   │   ├── Iteration.tsx
│       │   │   ├── WordLibrary.tsx
│       │   │   ├── SyncStatus.tsx
│       │   │   ├── ProfileSettings.tsx
│       │   │   └── Preflight.tsx
│       │   ├── hooks/
│       │   │   ├── useTaskStream.ts
│       │   │   └── useApi.ts
│       │   └── stores/
│       │       └── tasks.ts     # zustand：全局任务状态
│       └── public/
├── Makefile                     # 新增 make web / make web-dev 目标
└── pyproject.toml               # 新增 [project.optional-dependencies].web
```

---

## 5. 后端关键设计

### 5.1 进程锁与启动

- `web/backend/lock.py`：把 `main.py` 行 75-116 的 `acquire_process_lock/release_process_lock` 抽出为可复用模块，`main.py` 改为从这里导入（零行为变化）。
- `web/backend/__main__.py`：
  1. `acquire_process_lock()`（同 CLI）
  2. 读取 `MOMO_USER` 或启动参数指定用户 → 走和 `main.py` 一样的 `config.reload` 路径锁定单用户
  3. `init_concurrent_system()` + `init_db()`
  4. `uvicorn.run(app, host="127.0.0.1", port=8765, workers=1)`  # **禁止 >1 worker**
  5. 信号处理走 `app.lifespan` 的 shutdown：`workflow.shutdown()` + `cleanup_concurrent_system()`

### 5.2 依赖注入 (`deps.py`)

单例资源在 `lifespan` 里创建、请求中用 `Depends` 注入：

- `get_active_user() -> str`（短期：进程启动时锁定；Phase 6：从 Session/JWT 解）
- `get_momo_api() -> MaiMemoAPI`
- `get_ai_client() -> GeminiClient | MimoClient`
- `get_workflow() -> StudyWorkflow`
- `get_iteration_manager() -> IterationManager`
- `get_task_registry() -> TaskRegistry`
- `get_logger() -> ContextLogger`

### 5.3 TaskRegistry + 进度事件

关键问题：`StudyWorkflow.process_word_list()` 是同步阻塞调用，内部用 `ThreadPoolExecutor` 做 AI 并发；所有进度通过 `self.logger.info(...)` 以字符串广播。Web 需要：

1. **接收请求立即返回 task_id**：路由处理器调用 `task_registry.submit(func, args)` → 后台线程池跑，立即返回 `{"task_id": "..."}`。
2. **捕获进度**：`LoggerBridge`（`logger_bridge.py`）：对现有 `ContextLogger` 打补丁/wrap，在 `set_context(task_id=...)` 后每次 `info/warning/error` 调用都把 `{level, msg, module, ts}` 推入 `task_registry.queues[task_id]`。
3. **结构化事件**（分批量关键事件加增强）：在 `StudyWorkflow._process_results` 等关键节点**新增** `self.logger.info(..., extra={"event": "batch_done", "progress": {"current": ..., "total": ...}})`（ContextLogger 已支持 extra kwargs，见 `study_workflow.py:303` 的 `module=` 参数用法）——前端优先渲染 `event` 字段，否则按纯文本显示。这是**最小侵入的结构化进度**改动。
4. **SSE 推送**：`GET /api/tasks/{id}/events` 用 `sse-starlette` 的 `EventSourceResponse`，从 `asyncio.Queue` 消费事件；`StreamingResponse` 也可行但推荐 `sse-starlette`（心跳 + 重连友好）。
5. **任务状态**：`pending | running | done | error | canceled`；`done` 后保留结果 30 分钟可供 SSE 回放新连接。
6. **取消**：`POST /api/tasks/{id}/cancel` → 设置取消标志；`process_word_list` 内部 `try/except KeyboardInterrupt` 已存在（行 370-374），我们复用这个路径：在 executor 的 future 上 `cancel()` 即可。

### 5.4 WebUIManager 适配

`core/study_workflow.py` 只用到 UI 的极少数方法（通过 `self.ui`）：搜一下会发现实际只有 `process_word_list` 里**没有**直接调用 UI。UI 主要被 `main.py` 和 wizard 使用。策略：

- `process_word_list` 由 Web 路由触发时，`StudyWorkflow` 可以**不传入 UI**（但构造签名要求了），我们传一个 `NullUIManager` 空实现即可。
- `ConfigWizard` 的 `run_setup`/`validate_*` 方法里有大量 `print()`/`input()`，**改造为"API 化的一步步对话"**：
  - `POST /api/users/wizard/start` → 返回 session_id + 第一步表单 schema
  - `POST /api/users/wizard/{session_id}/submit` → 返回下一步或最终结果
  - 每一步的联网校验（`validate_momo / validate_mimo / validate_gemini`）提取到独立函数复用，前端可以点"验证"按钮同步校验。
- 不改 `CLIUIManager`；`WebUIManager` 仅实现 `render_sync_progress` 转发到 task 队列，其余方法空实现/抛错。

### 5.5 REST API 清单（第一期）

| 方法 | 路径 | 语义 | 对应现有函数 |
| --- | --- | --- | --- |
| GET | `/api/session` | 当前锁定用户、配置摘要 | `ACTIVE_USER`, `AI_PROVIDER` |
| GET | `/api/preflight` | 体检（同步返回） | `core/preflight.run_preflight` |
| GET | `/api/study/today` | 今日任务列表 | `MaiMemoAPI.get_today_items` |
| GET | `/api/study/future?days=N` | 未来 N 天 | `MaiMemoAPI.query_study_records` |
| POST | `/api/study/process` | 触发一批处理，返回 task_id | `StudyWorkflow.process_word_list` |
| POST | `/api/study/iterate` | 触发智能迭代，返回 task_id | `IterationManager.run_iteration` |
| GET | `/api/words` | 分页列出 ai_word_notes | `ai_word_notes` 表 |
| GET | `/api/words/{voc_id}` | 单词笔记详情 | `database.momo_words.get_local_word_note` |
| GET | `/api/words/{voc_id}/iterations` | 迭代历史 | `ai_word_iterations` 表 |
| GET | `/api/sync/status` | 队列深度、最近 N 条冲突 | `SyncManager` + `sync_status=2` 查询 |
| POST | `/api/sync/flush` | 触发一次立即收尾 | `SyncManager.flush_pending_syncs` |
| GET | `/api/stats/summary` | AI 调用数、tokens、处理词数 | 从 `ai_batches`、`processed_words` 汇总 |
| GET | `/api/users` | 本机 profile 列表 | `ProfileManager.list_profiles` |
| POST | `/api/users/wizard/start` | 新建 profile 向导 | `ConfigWizard` 分步 API |
| GET | `/api/tasks/{id}` | 任务状态 | `TaskRegistry.get` |
| GET | `/api/tasks/{id}/events` | SSE 进度流 | 新建 |
| POST | `/api/tasks/{id}/cancel` | 取消 | 新建 |

所有接口：
- 短期内**不鉴权**，但 `uvicorn` 绑定 `127.0.0.1` 避免外网访问。
- 响应统一：`{ok: bool, data: ..., error?: {code, message}}`。
- Pydantic `schemas.py` 单文件集中定义，方便后续 `openapi-typescript` 生成前端类型。

---

## 6. 前端关键设计

### 6.1 技术选型

- **Vite + React 18 + TypeScript（严格模式）**
- **UI 组件**：shadcn/ui（Radix + Tailwind，复制即用，不锁包体）；图标用 `lucide-react`
- **路由**：`react-router-dom@6`
- **状态**：`@tanstack/react-query`（服务端状态，含缓存/轮询）+ `zustand`（全局 UI / 任务面板）
- **SSE**：自己写轻量 Hook `useEventSource<T>(url)`，不引入额外库
- **表单**：`react-hook-form` + `zod`（wizard 步骤 + profile 编辑）

### 6.2 页面与主要交互

| 页面 | 关键元素 |
| --- | --- |
| Dashboard | 卡片：今日数 / 未来 7 天数 / 薄弱词数 / 同步队列深度；最近 AI 批次耗时折线 |
| 今日任务 | 虚拟列表展示 today_items，顶部 `[全部处理]` 按钮 → POST `/api/study/process` → 打开 TaskDrawer，SSE 展示每个 batch 的 pipeline 4 步 |
| 未来计划 | 日期范围选择 → 调用 /future 预览 → 确认处理 |
| 智能迭代 | 薄弱词表（含 score / it_level / familiarity），`[启动迭代]` 按钮；迭代过程同样进 TaskDrawer |
| 单词库 | 搜索 + 按 sync_status/it_level 过滤；行展开显示 memory_aid / ielts_focus / discrimination；右侧抽屉编辑 memory_aid（POST 改 ai_word_notes） |
| 同步状态 | 队列深度、最近 20 条冲突 (sync_status=2)；每行提供"查看云端现值 vs 本地"对比；`[重试同步]` 按钮 |
| 用户设置 | 当前 profile 只读摘要（token 掩码）；"修改 API Key" 行内编辑 + 即时 validate；创建新用户走 wizard 抽屉 |
| 体检 | 一键运行 preflight → 展示 JSON 结果，失败项给 fix_hint |

### 6.3 TaskDrawer：SSE 消费

全局右下角浮出面板，当有活跃 `task_id` 时展开：
- 订阅 `/api/tasks/{id}/events`
- 渲染两栏：上方进度条（从结构化 `event=batch_done` 推导），下方滚动日志流
- 支持最小化 / 取消 / 完成后自动收起

---

## 7. 分阶段交付（建议）

| 阶段 | 目标 | 主要产出 |
| --- | --- | --- |
| **0. 脚手架** (1d) | 锁抽出、依赖加入、空壳可跑 | `web/backend/lock.py`、`web/backend/app.py`（/health）、`make web-dev` 能起空壳；`web/frontend/` Vite 空壳可 npm run dev |
| **1. 后端核心** (3-4d) | TaskRegistry + SSE + 只读 API | session/preflight/today/future/words/stats/sync/status 跑通；LoggerBridge + `/api/tasks/{id}/events` 手动验证 |
| **2. 前端骨架** (2-3d) | 路由 + 布局 + API 客户端 + TaskDrawer | Dashboard 读到真实数据；TaskDrawer 能演示 SSE（mock 任务） |
| **3. 主流程打通** (4-5d) | process / iterate 端到端 | 今日任务、未来计划、智能迭代三条主流程能触发 + 看进度 + 看结果 |
| **4. 二级功能** (3-4d) | 单词库、同步状态、体检、用户设置 | CRUD + 筛选 + wizard 分步 API |
| **5. 打磨 & 文档** (2d) | 打包、错误态、README | `make web-build` 打 SPA 到 `web/frontend/dist`，FastAPI 静态托管；更新 `docs/dev/AI_CONTEXT.md` 添加 Web 模块边界 |
| **6. 多租户（远期）** | config 请求级重构 + 登录 | 独立发起，见 §9 |

---

## 8. 关键复用点（不重造轮子）

| 现有函数/类 | 位置 | Web 层用途 |
| --- | --- | --- |
| `acquire_process_lock` | `main.py:75` | 抽到 `web/backend/lock.py`，两边共用 |
| `StudyWorkflow` | `core/study_workflow.py:22` | `/api/study/process` 直接包装 |
| `StudyWorkflow.process_word_list` | `:274` | 主流程，通过 LoggerBridge 出进度 |
| `IterationManager.run_iteration` | `core/iteration_manager.py:26` | `/api/study/iterate` |
| `MaiMemoAPI.get_today_items` | `core/maimemo_api.py:606` | `/api/study/today` |
| `MaiMemoAPI.query_study_records` | `:620` | `/api/study/future` |
| `run_preflight` | `core/preflight.py`（现有） | `/api/preflight` |
| `ProfileManager.list_profiles/delete_local_profile` | `core/profile_manager.py:72/50` | `/api/users` |
| `ConfigWizard.validate_momo/validate_mimo/validate_gemini` | `core/config_wizard.py:25/42/76` | wizard 校验接口单独抽 |
| `database.momo_words.get_local_word_note` | `database/momo_words.py:1081` | `/api/words/{voc_id}` |
| `database.momo_words.get_unsynced_notes` | `:417` | `/api/sync/status` 冲突列表 |
| `SyncManager.flush_pending_syncs` | `core/sync_manager.py:205` | `/api/sync/flush` |
| `ContextLogger`（日志 set_context） | `core/logger.py` | task_id 上下文穿透 |

---

## 9. 面向未来多用户的架构预埋（非第一期实施，但方案保留钩子）

第一期不做，但现在就设计好"未来怎么切过去"，避免日后大改：

1. **所有后端路由都通过 `Depends(get_active_user)` 拿用户名**，而不是直接 import `ACTIVE_USER`。短期 `get_active_user` 从进程启动参数返回单值；Phase 6 换成 `Depends(jwt_auth)` 解析 token。
2. **Workflow / DB 查询都通过工厂函数按 user 构造**，不要在模块顶层 cache 连接。短期工厂忽略 user 参数，直接返回单例；Phase 6 按 user 维护连接池。
3. **schemas.py 所有响应都显式带 `user_id` 字段**，前端从第一天就建立多用户心智。
4. **Phase 6 的真正工作**：把 `config.py` 的 `DB_PATH`、`MOMO_TOKEN` 等模块级常量改为 `get_user_config(user) -> UserConfig`，`database/connection.py` 里的 `_get_main_write_conn_singleton` 改为按 user 缓存。这是一个独立 PR，不和 Web 本身的推进耦合。

---

## 10. 风险与取舍

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| **msvcrt 在 UI 模块顶部 import** (`core/ui_manager.py:5`) | 非 Windows 环境直接崩溃；但因项目就是 Windows 优先，影响有限 | Web 版根本不 import `CLIUIManager`；如需跨平台把 msvcrt import 下沉到方法内（一行小改动） |
| **logger tee 性能** | 高频事件可能灌爆 asyncio.Queue | TaskRegistry 队列设 maxsize（默认 1000）溢出时丢弃非关键日志并记一条 "truncated" 标记 |
| **单 worker 限制** | 同机器同时只能一个人用 | 本就是短期设定；Phase 6 上云时改云端 Turso，每用户隔离 DB，可横向扩 |
| **CLIUIManager 里的 `print()`** | 若 Web 后台 import 到 main.py 流程会污染 stdout | Web 后端入口**不经过** `main.py`，自行编排 `init_concurrent_system/init_db`，完全绕开 `StudyFlowManager.run()` |
| **wizard 从 input() 改为分步 API** | 改动较大且容易漏分支 | 第一期可以先用"单页表单一次性提交"，wizard 只拆为"提交后端 → 后端跑完整套校验 → 返回结果列表"，后续再做多步动画 |
| **进程锁冲突提示体验差** | Web 启动失败只打印在日志 | `__main__.py` 捕获锁获取失败，输出带排查步骤的中文提示；前端 dev 代理失败时显示 "后端未启动" 的骨架 |

---

## 11. 验证方式（端到端）

交付每个阶段都要能跑这些检查：

**阶段 0（脚手架）**
```bash
# CLI 仍可用
python main.py --help
# Web 空壳起
python -m web.backend --user <you>
curl http://127.0.0.1:8765/api/health     # {"ok": true}
# 前端空壳
cd web/frontend && npm install && npm run dev   # http://localhost:5173 可开
```

**阶段 1-2（后端 + 前端骨架）**
```bash
curl http://127.0.0.1:8765/api/session    # 返回当前用户 / AI_PROVIDER
curl http://127.0.0.1:8765/api/study/today
curl http://127.0.0.1:8765/api/stats/summary
# 前端 Dashboard 页面显示上述字段
```

**阶段 3（主流程）**
- 浏览器点 "今日任务 → 全部处理"
- TaskDrawer 弹出并显示 SSE 推送的 Pipeline 日志（对应 study_workflow.py:268/303/349/263 的 4 步）
- 处理完成后：`data/history-<user>.db` 的 `ai_word_notes` 新增条目、`processed_words` 新增、`sync_status` 逐步从 0→1
- 用 `python -m tools.preflight_check --format json` 交叉核对连通性未变

**阶段 4**
- 单词库分页查询 + 筛选工作
- `/api/preflight` 与 `tools/preflight_check.py --format json` 输出一致
- Wizard 创建新用户 → `data/profiles/<new>.env` 正确生成（内容与 CLI wizard 产出对齐）

**回归**
```bash
python -m pytest tests/ -v --tb=short -m "not slow"
```
保持全绿（Web 改动不破坏现有 core/database 测试）。

---

## 12. 初版需要改 / 新增的文件清单

**新增**（全部在 `web/` 下）：
- `web/backend/__main__.py`、`app.py`、`deps.py`、`lock.py`、`tasks.py`、`logger_bridge.py`、`schemas.py`
- `web/backend/routers/{session,study,words,sync,users,preflight,stats,tasks}.py`
- `web/backend/adapters/web_ui_manager.py`
- `web/frontend/` 整个 Vite 工程

**微调**（极小）：
- `main.py`：`acquire_process_lock/release_process_lock` 改为从 `web.backend.lock` 导入（行为等价）
- `pyproject.toml`：新增 `[project.optional-dependencies].web = ["fastapi", "uvicorn[standard]", "sse-starlette", "pydantic>=2"]`
- `requirements.txt`：同步新增（或留在 optional-dependencies 里，用 `pip install -e ".[web]"` 装）
- `Makefile`：新增 `web-dev` / `web-build` / `web-serve` 目标
- （可选）`core/ui_manager.py:5` 把 `import msvcrt` 下沉到 `check_esc_interrupt` 方法里，便于 Web 后端在非 Windows 环境跑

**不改**：`config.py`、`core/study_workflow.py`、`core/sync_manager.py`、`core/iteration_manager.py`、`core/maimemo_api.py`、`database/*`（仅做新增的结构化 `extra={"event": ...}` 可选增强，保持向后兼容）

---

## 13. 一句话总结

**复用现有业务核心，做一个 FastAPI + React SPA 的单进程 Web 包装层**：Web 后端抢占与 CLI 同一把进程锁，通过 TaskRegistry + 日志 tee 把现有基于日志的进度通信转成 SSE 流，第一期锁定单用户兼容现状，第二期再把 config 模块级全局重构为请求级上下文以支持多租户云部署。

---

## 14. 初始化步骤

进入实施前，先把本方案文档正式落到仓库，后续所有 Web 相关改动都在专用分支上推进：

1. **基线检查**：当前分支 `main`，工作区除 `.codex/`（非追踪）外无其他改动。
2. **创建开发分支**：`git checkout -b feat/web-ui`（从 `main` 拉出；后续若分大阶段可在此基础上再开 `feat/web-ui-backend`、`feat/web-ui-frontend` 等子分支）。
3. **归档方案文档到仓库**：把本方案完整复制到 `docs/dev/WEB_UI_PLAN.md`（与现有 `docs/dev/` 下 `AUTO_SYNC.md`、`AI_CONTEXT.md` 同目录，便于后续维护者查阅）。
4. **提交**：`git add docs/dev/WEB_UI_PLAN.md`；commit message 用项目常用中文前缀风格。
5. **暂不推送远端、暂不动现有代码**：推送 / 后续脚手架落地由下一个 PR 承担。

这一步**只做文档落地 + 分支创建**，不动任何 `core/` / `database/` / `main.py` / `pyproject.toml`。
