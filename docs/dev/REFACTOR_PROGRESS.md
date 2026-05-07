# 【MoMo_Script】代码瘦身、文档规范化与架构重构实施计划与进度

本文档用于跟踪系统架构重构的全面进度，方便在多个开发 Session 之间保持上下文一致。

## 整体进度 (Overall Progress)

- `[ ]` Phase 1: 数据库层重构与瘦身（Phase 1.5 行为不变瘦身仍未完成）
- `[x]` Phase 2: Web 路由解耦与前端状态规范化
- `[x]` Phase 3: 全局目录规范化与测试体系重组
- `[ ]` Phase 4: Path B 调度地基
- `[ ]` Phase 5: 日志系统整合与可观测性优化
- `[ ]` Phase 6: 工程底座与防腐机制

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
- `[ ]` 将 `execution_engine.py` 中的 `queue.Queue` 升级为 `asyncio.PriorityQueue`。
- `[ ]` 支持基于 Profile 上下文发出 `Promotion=True` 的插队写入指令。

### Phase 5: 日志系统整合与可观测性优化
- `[ ]` 废除 `database/connection.py` 和 `utils.py` 中重复发明的 `_debug_log_throttled` 字典逻辑。
- `[ ]` 在 `core/logger.py` 中提供原生的 `warning_throttled` API。
- `[ ]` 激活 `LogStatistics` 并将其钩子挂载到执行引擎，自动捕获耗时 SQL 与高频异常。

### Phase 6: 工程底座与代码防腐机制
- `[ ]` **配置现代化**：废除 13KB 的 `config.py`，迁移至 `pydantic-settings` 获取强类型校验。
- `[ ]` **Schema 迁移**：建立基于 SQLite `user_version` 的平滑演进机制，不再依赖 `CREATE TABLE IF NOT EXISTS`。
- `[ ]` **CI/CD**：引入 `Ruff` (后端) 和 `ESLint` (前端) 到 pre-commit hook 进行严格的代码纪律拦截。

---

*注：在开发过程中，请持续维护本文档中 Checkbox 的状态。*
