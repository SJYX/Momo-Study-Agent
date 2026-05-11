# 【MoMo_Script】代码瘦身、文档规范化与架构重构实施计划与进度

本文档用于跟踪系统架构重构的全面进度，方便在多个开发 Session 之间保持上下文一致。

## 整体进度 (Overall Progress)

- `[ ]` Phase 1: 数据库层重构与瘦身（Phase 1.5 行为不变瘦身仍未完成）
- `[x]` Phase 2: Web 路由解耦与前端状态规范化
- `[x]` Phase 3: 全局目录规范化与测试体系重组
- `[x]` Phase 4: Path B 调度地基（sync_queue 优先级 + per-profile 暂停）
- `[x]` Phase 4.5: API 查询降重（PLAYBOOK A1，解决"页面打开卡"的根因）
- `[x]` Phase 5: 日志系统整合与可观测性优化（路线 C+A：清重复 + 轻量诊断；不激活 LogStatistics，留待 Phase 6 SLO）
- `[x]` Phase 6: 工程底座与防腐机制（Kill Switch / Schema user_version / config 重构 / lint hook）

---

## 阶段详情与微观任务 (Detailed Tasks)

### Phase 1: 数据库层重构与瘦身
- `[x]` 新建 `database/execution_engine.py`，负责后台队列消费与防写冲突。
- `[x]` 将 `database/connection.py` (1100+行) 剥离为纯粹的配置映射和连接池。
- `[x]` 封装 `@with_read_session`, `@with_write_session` (或 Context Manager)。
- `[x]` 下沉兜底：将 `momo_words.py` 业务代码中长达 70 行应对 SQLite 损坏的重试逻辑提取到底层统一拦截器。
- `[x]` 重写 `database/momo_words.py` (1300+行)，大幅消除冗余模板代码。
- `[ ]` Phase 1.5（行为不变瘦身）：按职责拆分 `momo_words.py` 为 `notes_repo.py` / `progress_repo.py` / `community_lookup.py` / `sync_service.py`，`momo_words.py` 仅保留兼容导出。
- `[ ]` 抽取 `build_note_upsert_args(payload, metadata)`，统一单条与批量写入参数组装，消除重复字段拼装。
- `[ ]` 抽取统一行映射工具（如 `row_to_dict_safe`），替换散落在各函数中的 `row` 转字典模板代码。
- `[ ]` 抽取统一写入分发层（本地直写 vs 队列写），收敛重复分支模板逻辑。
- `[ ]` 收紧异常策略：减少宽泛 `except Exception` 吞错，按可预期异常分类处理并保留结构化日志。
- `[ ]` 引入 repo 层 DTO（`TypedDict` / `dataclass`）与集中化 SQL 常量，降低字典魔法字段与散落 SQL 维护成本。
- `[ ]` 为 `sync_databases` / `sync_hub_databases` 提取共享模板（连接、状态、回调、异常映射），减少重复同步流程代码。
- `[ ]` 新增 `tests/unit/database/` 真实单元测试，覆盖参数组装一致性、双写路径一致性、异常恢复分支。

### Phase 2: Web 路由解耦与前端状态深度规范化

> 说明：原计划 4 项与代码实际状态走查后重排为 6 项（A-F + 文档同步 G）。原"router 中手动锁上下文"实际只在 study.py 一个文件，已被 helper 收敛——真问题是封装泄漏；原"建立 components/ui/ 原子组件库"在没有调用方时是 yak shave，改为按需收割（≥3 次重复才抽）。新增项："router 异常装饰器"（消除 8+ 处 try/except 模板）和"4 个 fat page 的 React Query 迁移"（计划遗漏的真重复）。

- `[x]` **A 后端**：新建 `web/backend/router_helpers.py` 提供 `@catch_api_errors` 装饰器，替换 study/words/users/sync 四个 router 的 8 处 `try/except → error_response("XXX", str(e), user_id=user)` 外层模板。
- `[x]` **B 后端**：在 `web/backend/lock.py` 暴露 `claim_profile_lock_with_placeholder` / `update_profile_lock_holder` 两个公开 API，下沉 `_submit_with_profile_lock` 中对 `_profile_locks_guard` / `_profile_lock_holders` 私有变量的直接访问（封装泄漏修复）。原计划的 `@require_profile_lock` 装饰器在实际场景下不成立（锁需要 task_id 占位 → 真实 ID 替换 + 终态回调 + 409 抛出），保持 helper 函数形态。
- `[x]` **C 前端**：新建 `web/frontend/src/queries/queryClient.ts`（QueryClient + queryKeys 工厂）、在 `main.tsx` 包 `QueryClientProvider`；改造 `Preflight.tsx` / `SyncStatus.tsx` 两个样板页，移除手写 `useState<Data>(null) + useEffect+fetch` 模板。`apiClient` 的 throw Error 行为天然匹配 React Query，无需额外适配器；与 SSE (`useTaskStream`) 边界明确：React Query 只管「拉一次/轮询」类 GET，事件流不接管。
- `[x]` **D 前端**：抽出 `web/frontend/src/hooks/useTodayController.ts` 承接 TodayTasks.tsx 全部状态机（13 处 useState、4 处 useEffect、若干 useMemo），TodayTasks.tsx 从 404 行减至 228 行（-44%），主组件回归为纯渲染。DOM ref Map 仍由组件持有（hook 不直接访问 DOM）。
- `[x]` **E 前端**：将 React Query 推到剩余 4 个 fat page —— `Users.tsx` (382)、`WordLibrary.tsx` (316)、`UserGateway.tsx` (341)、`OpsMonitor.tsx` (414)。`OpsMonitor` 的手写 setTimeout 轮询替换为 `useQuery` 的 `refetchInterval` + `refetchIntervalInBackground=false`。`useOpsPolling` / `useTaskStream` 保留不动（前者后续可选迁移；后者是 SSE，边界外）。
- `[x]` **F 前端**：按需收割 UI 原子。实际重复扫描后只有 error banner 跨 9 处出现 ≥3 次的相同 className，抽到 `web/frontend/src/components/ui/ErrorBanner.tsx`。按钮变体太多（每处 size/spacing 不同），徽章每处 color 不同——不强行抽 atom 避免引入伪规范化。预计 Phase 3+ 中若出现新重复再继续收割。
- `[x]` **G 文档**：本节已同步重排后的 6 项（用户已确认）。

**测试**：
- 后端 `pytest tests/web/`：157 passed（含新增 `test_router_decorators.py` 12 用例 + `test_lock_api.py` 8 用例）
- 前端 `npx tsc -b`：0 error
- 前端 `npm run test`：48 passed
- 前端 `npm run build`：production bundle 365.65 kB（gzip 108.56 kB），构建成功

### Phase 3: 全局目录规范化与测试体系重组

> 说明：原计划 5 项与代码实际状态走查后重排为 9 项（A-I）。原"node_modules"是 codex 调试残留（19MB）；原"main.py 10KB+"准确，但真痛点是 80 行 `StudyFlowManager` 业务编排塞在入口里，应抽到 core/，而不是改名 `src/server.py`；原"`tests/unit/` `tests/integration/` 划分"已部分完成（Phase 1.5 已建好），真任务是 tests/ 根 13 个散文件归类；docs 真问题比计划描述严重——14 个 dev 文档 + 5 处 WEB_UI* 重复，且根目录 5 个 md 角色重叠。

- `[x]` **A 清理根 codex 残留**：删除根 `node_modules/`（19MB）+ `package.json`（仅一个 `codex@^0.2.3` 依赖）+ `package-lock.json`。`.gitignore` 已含 `node_modules/`，未来不会再次进入。
- `[x]` **B 移走 scratch 与实验脚本**：`./test_concurrency_refactor.py`（根） + `tests/experiments/` 7 个手动脚本搬到 `scripts/scratch/`（含 `experiments/` 子目录 + `README.md` 说明用途）。pytest 不再扫这些文件，避免误收集。
- `[x]` **C tests/ 根 13 个散文件按 unit/integration 归类**：
  - `tests/unit/logging/`：test_async_logging / test_logger / test_logger_dynamic / test_log_compression / test_log_statistics / test_performance
  - `tests/unit/config/`：test_config_system
  - `tests/unit/database/`（Phase 1.5 已建）保持不变
  - `tests/integration/logging/`：test_full_integration
  - `tests/integration/bootstrap/`：test_init / test_multi_environment
  - `tests/integration/database/`：test_robustness
  - `tests/integration/pipeline/`：test_mimo_pipeline / test_raw_fix
  - 修复了 `tests/integration/__init__.py` 缺失导致的命名冲突（`logging` / `database` 子目录与 stdlib / 项目 package 同名）。
- `[x]` **D 集成测试 in-memory fixture**：新建 `tests/integration/conftest.py`，提供 `memory_sqlite_db`（单连接 :memory:）+ `shared_memory_sqlite_uri`（多连接共享内存 DB URI）两个 fixture，配套写 `tests/README_TESTING.md` 第 6 节解释何时用什么。**不批量改造现有测试**，仅给后续新写的纯 SQLite 集成测试用。
- `[x]` **E main.py 真瘦身**：`StudyFlowManager` 抽到 `core/study_flow.py`（143 行），`_build_ai_client` 抽到 `core/factories.py`（37 行），main.py 从 252 行降至 89 行（-65%），只保留 EARLY BOOTSTRAP / argparse / `acquire_process_lock` 调用。同步更新 `tests/core/test_main_flow.py` 的 patch 路径（`main.X` → `core.study_flow.X`）。CLI 行为完全不变。
- `[x]` **F scripts 清理**：4 个 debug 脚本（`_debug_backend.py` / `_debug_er.py` / `debug_http_db.py` / `debug_turso.py`）grep 验证无引用后归到 `scripts/scratch/debug/`。`scripts/dev_tools.py` 是 format/lint/test 入口，保留在主路径。`scripts/archived/` 已有自己的 README，保持现状。
- `[x]` **G docs/dev/ 整合**：归档 4 个根级 `WEB_UI_*` 旧版（被 `docs/dev/web_ui/` A+ 工作区取代）到 `docs/history/web_ui_legacy/`；更新 CLAUDE.md / AI_CONTEXT.md / ARCHITECTURE.md 三处引用指向新版 `web_ui/README.md`；新建 `docs/dev/DEVELOPMENT.md` 作为**纯导航索引**（绝不复制其他文档内容，避免事实源漂移）。docs/dev/ 从 14 个文件降至 12 个（-WEB_UI* 4 个，+DEVELOPMENT.md 1 个）。
- `[x]` **H 根目录 5 个 md 整合**：归档 `PROJECT_STATUS.md`（已严重过期，仍在引用 2026-04-22 删除的 `db_manager.py`）到 `docs/history/snapshots/PROJECT_STATUS_2026-04-25.md`；`README.md` 末尾追加开发者文档导航；`AGENTS.md` 顶部加交叉引用，明确"项目业务地图见 CLAUDE.md，本文件只约束代理工作方式"；`CLAUDE.md` 与 `CHANGELOG.md` 保持现状（角色清晰）。
- `[x]` **I src/ 后端迁移决策**：见下方决策段落。

> **关于 src/ 后端迁移**：本期评估后**暂不实施**，但**不定调为永久不做**。
>
> 评估结论：
> - 影响面大：所有 `from database.x import y` / `python -m core.x` 调用、Makefile (`make web`)、CLAUDE.md / AI_CONTEXT.md 文档引用、外部脚本可能 hardcoded 的根目录布局、CI（如有）
> - 收益是纯结构标准化，无具体痛点支撑（当前 root 包布局对 Python 项目而言完全可用）
> - ROI 不足，且会消耗 5-7 个 PR 才能验证完整性
>
> 决策保持开放——后续若引入新的强约束（如 monorepo 工具规范、CI 标准化要求、依赖管理工具升级）再重启评估。

**测试**：
- `pytest tests/`：281 collected，279 passed + 1 xpassed + 1 pre-existing 失败（test_iteration_lifecycle，Phase 1.5 即已存在）
- `python -c "from core.study_flow import StudyFlowManager; from core.factories import build_ai_client"`：通过
- 所有 docs 链接验证可达

### Phase 4: Path B 调度地基

> 说明：原计划 2 项与 PLAYBOOK / MATRIX / 代码现状走查后重排为 5 项（A-E）。
>
> 关键修订：
> 1. **目标队列改正**：原计划写"`execution_engine.py` 中的 `queue.Queue` 升级为 `asyncio.PriorityQueue`"指错对象——PLAYBOOK Path B 说的是 maimemo 同步队列（`core/sync_manager.py::sync_queue`），而非 SQLite 写队列。SQLite 写队列已是批量 commit，加优先级几乎无收益。
> 2. **threading 模型**：保持现状，使用 `queue.PriorityQueue`（标准库 threading 安全），不引入 asyncio——会与现有 `threading.Thread` worker、`threading.Lock` 频控混用，复杂度暴增收益为 0。
> 3. **"全局单消费者"叙事放弃**：当前架构是 N 个 profile = N 个独立 SyncManager worker，无法"全局排队"。改为 **per-profile 单消费者 + 进程级 ActiveProfileRegistry**，非 active profile 的 P3+ 任务暂停拉取。
> 4. **闲时引擎 / 可观测性 / 前端协同 推迟**：依赖 Phase 5 监控基础设施或属于前端独立工作，不在"调度地基"范围。

**WIP 进度（2026-05-09，本次 session 截止）**：

| 子任务 | 状态 |
|---|---|
| **A** sync_queue → PriorityQueue | ✅ 已完成（`queue.PriorityQueue` + `(priority, seq, payload)`，shutdown 改 `_stop_event`） |
| **B** 4 处调用点注入优先级 | ✅ 已完成（study_workflow/study_flow=P1，sync retry=P2，warmup=P3） |
| **C** 防饿死保底 | ✅ 已完成（连续 5 个 P1 后强制让出 1 个非 P1） |
| **D** ActiveProfileRegistry | ✅ 已完成（deps `set_active` 接入 + worker 出队前 active 自检） |
| **E** 单元测试 | ✅ 已完成（新增 `tests/unit/sync_manager/` 三个用例） |
| 辅助 | ✅ `core/sync_priority.py` Priority IntEnum 已建 |

**Phase 4.5 已完成**：API 查询降重（COUNT 替代全量 fetch）。

- `[x]` **A**：`core/sync_manager.py` 的 `sync_queue` 由 `queue.Queue` 升级为 `queue.PriorityQueue`。任务条目封装为 `(priority_int, seq, payload)`，`seq` 单调递增保证同优先级 FIFO 并避免 dict 比较 TypeError。**shutdown 改用 `_stop_event` + 短 timeout 轮询**（取代原计划的 sentinel 方案），更干净并与 `database/execution_engine.py` 一致。
- `[x]` **B**：4 处调用点注入优先级——
  - `core/study_workflow.py:285` → P1（今日任务）
  - `core/study_flow.py:66` → P1（今日任务）
  - `web/backend/routers/sync.py:145` → P2（用户主动）
  - `web/backend/user_context.py:244`（`_warmup_async`）→ P3（warmup 补偿）
- `[x]` **C**：worker 防饿死保底——维护 `consecutive_p1_count`，连续 5 个 P1 后强制让出 1 个 P2/P3。
- `[x]` **D**：~~新建 `core/active_profile_registry.py` 进程级单例~~（已建，✅）；在 `web/backend/deps.py::_resolve_profile()` 末尾调用 `set_active(profile)`；SyncManager worker 出队前自检：非 active profile 且 priority ≥ P3 则重新入队 + sleep 0.5s 后 continue。
- `[x]` **E**：单元测试 `tests/unit/sync_manager/`：
  - `test_priority_order.py`：P1 先于 P2 先于 P3 出队；同优先级 FIFO
  - `test_starvation.py`：连续 5 个 P1 后强制让 1 个 P2
  - `test_active_profile_pause.py`：非 active profile 的 P3 任务被暂停拉取，切换 active 后立即处理

**不做（明确划界）**：
- ✗ `execution_engine._write_queue` 不动
- ✗ 不引入 asyncio
- ✗ 不做 60/25/15 加权（过度设计）
- ✗ 不做批次级抢占（粒度对不上 maimemo HTTP 同步）
- ✗ 不做全局单消费者（架构改造太大）
- ✗ Kill Switch 配置 → Phase 6
- ✗ 闲时引擎 / SLO 告警 → Phase 5
- ✗ 前端 hover prefetch → 独立 web_ui 工作

### Phase 4.5: API 查询降重（PLAYBOOK A1）

> 说明：Phase 4 调度地基只解决"多 profile 同步互相干扰"问题，**真正让用户感知"页面不卡"的根因是 API 接口里的全表扫描**。本阶段独立成 Phase 4.5，与 Phase 4 解耦但紧随其后实施（建议同一周完成），是 hover prefetch 的硬前置。

- `[x]` `GET /api/stats/summary` 中"待同步数量"改为 `COUNT(*)`（`ai_word_notes` + `sync_status=0` + `content_origin='ai_generated'`），禁止 `len(get_unsynced_notes())`。
- `[x]` `GET /api/sync/status` 队列深度改为 `COUNT(*)`（同口径）。
- `[x]` 冲突列表 endpoint 默认 `limit=20`，强制分页（`/api/sync/status` 已验证默认返回 20 条冲突）。
- `[x]` 全仓 grep 检查：高频 GET 接口已完成排查；计数路径改为 SQL `COUNT(*)`，未保留 `SELECT *` 后再 `len(...)` 的队列计数实现。
- `[x]` 验收（本期可执行部分）：相关后端测试通过（`tests/web/test_stats.py`、`tests/web/test_sync.py`），并完成全量回归（`280 passed, 3 skipped, 1 xpassed, 1 failed`）；当前仅保留 1 个既有失败 `tests/core/test_iteration_manager.py::test_iteration_lifecycle`。P95<100ms 需 Phase 5 监控落地后量化。

### Phase 5: 日志系统整合与可观测性优化

> 说明：原计划 3 项与代码现状走查后重排为 2 项（5.1 + 5.2）。
>
> 关键修订：
> 1. **路线选定为 C+A**（清重复代码 + 开发期轻量诊断）。**不**激活 `LogStatistics`——它是会话内无界累积计数器，没有滚动窗口、reset、读取端，激活意义不大；真要做指标系统应到 Phase 6 SLO 一起做。
> 2. **原 1+2 合并**：`_debug_log_throttled` 之所以重复，是因为没有中央 API。把 `*_throttled` 落到 `ContextLogger`，5 处调用点直接迁移，两份私有实现 + 私有 dict + 私有 Lock 全删。Item 1 自然死亡。
> 3. **新增"挂载点"语义澄清**：原"挂载到执行引擎自动捕获耗时 SQL"是新工作不是激活——`_execute_batch_writes` 现在不发 `duration_ms`。改为直接在批写完成 / 闲时 sync 完成处发结构化 INFO/WARNING 日志（带 `batch_size` / `duration_ms` / `is_slow`），grep/excel 离线分析足够，**不**走 LogStatistics 通道。

- `[x]` **5.1** `core/logger.py::ContextLogger` 加 `debug_throttled` / `info_throttled` / `warning_throttled` / `error_throttled` 共 4 个节流方法（共享同一 throttle dict + Lock，进程级唯一 key 命名空间）；迁移 5 处调用点：
  - `database/session.py` 3 处（`with_read_session` 损坏恢复 WARNING / 损坏最终 ERROR / `with_write_session` 写损坏 WARNING）
  - `database/connection.py` 2 处（`_hub_fetch_one_dict` / `_hub_fetch_all_dicts` 损坏 WARNING）
  
  删除 `database/connection.py` 的私有 `_debug_log_throttled` + `_throttled_log_state` + `_throttled_log_lock`；删除 `database/utils.py` 同名三件套。`database/utils.py` 不再 export `_debug_log_throttled`，`database/session.py` import 同步收紧。
- `[x]` **5.2** 在 `database/execution_engine.py` 加结构化耗时日志：
  - `_execute_batch_writes` 成功路径末尾发一条日志，extra 含 `batch_size` / `duration_ms` / `retries` / `is_slow`；`duration_ms >= 100ms` 升级为 WARNING（与 Phase 4.5 P95<100ms 阈值对齐）
  - `_sync_daemon` 闲时 sync 成功路径同样发结构化日志，`duration_ms >= 500ms` 升级为 WARNING（远端往返 + commit 视为合理上限）
  - **不**接入 LogStatistics；离线 grep `module=database.execution_engine` + `is_slow=true` 即可定位慢路径。

**不做（明确划界）**：
- ✗ 激活 `LogStatistics`（无界累积 + 无消费者，激活无收益）
- ✗ 滚动窗口 / 周期 dump / `/api/ops/log-stats` endpoint —— 留给 Phase 6 SLO
- ✗ `_debug_log` 三处副本合一（连接层依赖松散，机会主义清理留给后续）

**测试**：
- 触及模块 `python -m py_compile`：通过（`core/logger.py` + `database/{connection,utils,session,execution_engine}.py`）
- `pytest tests/ -m "not slow"`：**278 passed**, 3 skipped, 1 xpassed, 3 failed
- 3 failed 全为既有失败，与 Phase 5 改动无交集：
  - `tests/core/test_gemini_client.py` ×2 — 环境依赖问题（`google.genai` → `aiohttp.ClientResponse` 不存在）
  - `tests/core/test_iteration_manager.py::test_iteration_lifecycle` — Phase 4.5 即标注为既有失败
- `tests/integration/pipeline/test_raw_fix.py` 同样收集失败（`aiohttp` 兼容），用 `--ignore` 跳过

### Phase 6: 工程底座与代码防腐机制

> 说明：原计划 3 项与代码现状走查后重排为 4 个子阶段（6.1–6.4）。
>
> 关键修订：
> 1. **PLAYBOOK A4 Kill Switch 提前独立**（6.1）：3 个 flag 用 `os.getenv` 一行落地比等整个 Phase 6 套餐快得多，6.3b 时再合并到 pydantic-settings。
> 2. **原"废除 13KB config.py"框架不准确**：273 行里大部分是 profile 生命周期 + hot-swap 业务逻辑（三阶段 env load / 路径兜底 / `switch_user` 反向 patch 数据库模块），pydantic-settings 不解决这部分。改走路线 1B：先抽 `core/profile_loader.py`（6.3a），再把真正的"静态 settings"走 pydantic（6.3b）。
> 3. **原"建立基于 SQLite user_version 的平滑演进机制"描述准确但严重欠规格**：现状全部 `CREATE TABLE IF NOT EXISTS` + try/except 静默吞 "duplicate column" + 数据回填每次启动跑。本期目标是建框架打底（runner + V001 收纳现存 ALTER + 存量 DB 标签到 v1 + 硬抛 duplicate column），不要求把所有现存逻辑都迁干净。
> 4. **原"引入 Ruff"过时**：Ruff 已在 [pyproject.toml:65-123](../../pyproject.toml#L65-L123) 配置好；真任务是写 `.pre-commit-config.yaml` 和前端 ESLint 把它启用。

#### 6.1 PLAYBOOK A4 Kill Switch 提前落地

- `[x]` 新建 `core/feature_flags.py`：`is_enabled(name, default=True)` 读 `os.getenv` + 进程级缓存 + `set_enabled` 测试钩子
- `[x]` `AUTO_WARMUP_SYNC_ENABLED` → 在 `web/backend/user_context.py::_warmup_async` 早返回（仅跳过扫描+入队，不影响同步段 schema 初始化）
- `[x]` `SYNC_STATUS_HEAVY_QUERY_ENABLED` → 在 `web/backend/routers/sync.py::sync_status` 跳过 COUNT/SELECT，返回占位 + `degraded: true`
- `[x]` `BACKGROUND_RETRY_ENABLED` → 在 `web/backend/routers/sync.py::retry_conflicts` 关闭时返回 503 风格 error_response
- `[x]` 单测 `tests/unit/feature_flags/test_kill_switch.py`：默认 True / env override / 测试钩子三态（16 用例）

#### 6.2 Schema 迁移框架（user_version）

- `[x]` 新建 `database/migrations/` 包：`runner.py`（读 PRAGMA + 顺序应用）+ `V001_initial.py`（收纳现存 ALTER + 初始建表）
- `[x]` 存量 DB 一律走完整迁移链：V001 是幂等的（`_column_exists` 检查 + `UPDATE WHERE IS NULL`），重跑安全。**放弃**了"v=0 + 表存在则直接打标签 v=1"的快捷路径——会漏掉 V001 中的 backfill UPDATE
- `[x]` Replica 策略：仅在写连接（singleton）跑迁移；PRAGMA user_version 通过 libsql sync 同步到本地副本
- `[x]` 改 `database/schema.py::_create_tables`：删除 ALTER 列表 + try/except "duplicate column" + 数据回填；保留 `CREATE TABLE IF NOT EXISTS` 作为 v0 setup
- `[x]` `init_db` 在两个分支（cloud / local）都调 `apply_migrations`，与 `_main_write_conn_op_lock` 共用串行边界
- `[x]` 单测 `tests/unit/database/migrations/test_runner.py`（6 用例）：target_version / 空 DB / 全新 DB → v1 / 幂等重跑 / 老 DB 缺列补齐 / V999 失败回滚

#### 6.3 配置层重构（路线 1B：抽 profile orchestration → 局部 pydantic-settings）

- `[x]` **6.3a** 新建 `core/profile_loader.py`，抽 `config.py` 中：
  - `normalize_username` / `resolve_profile_env_path` / `resolve_user_db_paths`
  - 三阶段 env 加载（global → user → reload global for FORCE_CLOUD_MODE）打包为 `bootstrap_initial_profile`
  - `switch_user(...)` 计算部分（不含跨模块 patch）
  - `config.py` 缩减为：路径常量 + UTF-8 hack + bootstrap 调用 + 静态 settings 导出 + `switch_user` thin wrapper（仍含跨模块 patch，作为已知 wart 留待后续清理）
  - 新 `pyproject.toml` 顶层依赖：`pydantic>=2.0.0` / `pydantic-settings>=2.0.0`
- `[x]` **6.3b** 新建 `core/settings.py`：`Settings` 模型覆盖 API keys + Turso URLs + 重试常量 + Kill Switch flags（共 23 字段）
- `[x]` `feature_flags.is_enabled` 改为优先走 `core.settings.get_settings()`，env / settings 验证失败时降级到 raw `os.getenv`，保留 `set_enabled` 测试钩子语义不变
- `[x]` `rebuild_settings()` 失败时清空 `_settings` 缓存避免误用旧实例
- `[x]` 单测 `tests/unit/profile_loader/test_profile_loader.py`（8 用例）+ `tests/unit/settings/test_settings.py`（7 用例）

#### 6.4 pre-commit + ESLint 启用

- `[x]` 新建 `.pre-commit-config.yaml`：trailing-whitespace / end-of-file-fixer / check-yaml / check-toml / check-added-large-files / check-merge-conflict + ruff lint + ruff format + 前端 local hooks（eslint / tsc -b）
- `[x]` 新建 `web/frontend/eslint.config.js`：ESLint 9 flat 配置，含 typescript-eslint + react + react-hooks 规则
- `[x]` `web/frontend/package.json` 加 `lint` / `lint:fix` script + `eslint`/`@eslint/js`/`typescript-eslint`/`eslint-plugin-react`/`eslint-plugin-react-hooks` 到 devDependencies
- `[x]` `docs/dev/CONTRIBUTING.md` 顶部加"一次性环境设置"小节，含 `pip install -e ".[dev,web]"` + `pre-commit install` + `npm install`
- 不做：`pre-commit install` 由 user 自行跑（修改 `.git/hooks/`，不应自动）；`npm install` 同理；GitHub Actions 留独立 PR

**测试**：
- `pytest tests/`（不含 aiohttp/genai 受损的 gemini 与 pipeline）：**312 passed**, 3 skipped, 1 xpassed, 1 既有失败 (`test_iteration_lifecycle`)，**0 新回归**
- 新增 37 个单元测试：feature_flags 16 + migrations 6 + profile_loader 8 + settings 7
- 触及模块 `python -m py_compile`：通过

---

*注：在开发过程中，请持续维护本文档中 Checkbox 的状态。*
