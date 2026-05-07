# 【MoMo_Script】代码瘦身、文档规范化与架构重构实施计划与进度

本文档用于跟踪系统架构重构的全面进度，方便在多个开发 Session 之间保持上下文一致。

## 整体进度 (Overall Progress)

- `[ ]` Phase 1: 数据库层重构与瘦身
- `[ ]` Phase 2: Web 路由解耦与前端状态规范化
- `[ ]` Phase 3: 全局目录规范化与测试体系重组
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

### Phase 2: Web 路由解耦与前端状态深度规范化
- `[ ]` **后端**：剥离 FastAPI Router 中手动处理锁上下文代码，引入 `@require_profile_lock` 装饰器。
- `[ ]` **前端**：全量落地 `React Query` (移除手动的 `useState` / `useEffect` 获取数据流)。
- `[ ]` **前端**：拆解 `TodayTasks.tsx` (400+行 Fat Component)，分离逻辑 Hook 和渲染层。
- `[ ]` **前端**：建立 `src/components/ui/` 的原子化组件库（如 `<Button>`, `<Badge>`）。

### Phase 3: 全局目录规范化与测试体系重组
- `[ ]` **Monorepo 清理**：移除根目录的 `node_modules` 和非 Python 构建产物。后端代码迁移入 `src/` (待定，视改动量而定)。
- `[ ]` **入口瘦身**：精简 10KB+ 的 `main.py`，启动逻辑剥离到 `src/server.py`。
- `[ ]` **垃圾清理**：将 `test_concurrency_refactor.py` 及 `tests/experiments/` 移入 `scripts/scratch/`。
- `[ ]` **测试体系**：划分 `tests/unit/` 与 `tests/integration/`，引入 `sqlite :memory:` 支持纯粹脱盘测试。
- `[ ]` **文档整合**：归档旧文档，建立全局唯一开发指引 `docs/dev/DEVELOPMENT.md`。

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
