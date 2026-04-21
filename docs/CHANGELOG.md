# 文档更新日志

记录 Momo Study Agent 项目文档的变更历史。

## 2026-04-21

### 文档大清理（docs/cleanup 分支）

完整方案与执行结果见 [`history/phases/DOCS_CLEANUP_PLAN.md`](history/phases/DOCS_CLEANUP_PLAN.md)。

**归档到 `docs/history/phases/`**（脱离活动目录，AI 会话不再误读为当前任务）：
- `PHASE_2_WRITE_SIMPLIFICATION.md`、`PHASE_3_SYNC_OPTIMIZATION.md`、`PHASE_4_TESTING_VALIDATION.md`
- `EMBEDDED_REPLICAS_PHASE_0_2_COMPLETION.md`、`EMBEDDED_REPLICAS_MIGRATION.md`（从 `architecture/` 移入）
- `OPEN_SOURCE_TRANSITION_PLAN.md`
- `WAL_CONFLICT_FIX.md`、`CONCURRENCY_REFACTOR.md`（从 `docs/` 根移入）
- 新增 `history/phases/README.md` 索引，列每份归档的历史意义 + 当前代码替代位置。

**合并与重写：**
- `architecture/OVERVIEW.md` + `SYSTEM_ARCHITECTURE.md` + `DATA_FLOW.md` 三合一为 `architecture/ARCHITECTURE.md`（含从 CONCURRENCY_REFACTOR 提炼的并发模型段 + 从 EMBEDDED_REPLICAS_MIGRATION 提炼的同步模型段）。
- `database/README.md` 去掉头部孤悬的次级标题，将游标协议/写事务/GC hack 重组为 Runtime Iron Rules 小节；新增"本地 WAL 并发配置"与"批量写入重试守则"两节，吸收原 WAL_CONFLICT_FIX 的 PRAGMA 精华。
- `CLAUDE.md`（项目根）从 30 行指针页升级为 ~100 行 AI 会话首页：当前状态 / 模块地图 / 三条红线 / 找东西 / 调试定位 / 常用命令。

**断片修复：**
- `architecture/LOG_SYSTEM.md`：删除头部 9 行残余"Phase 3 运维优化总结"。
- `architecture/decision_flow.md`：§7 补齐缺失的大标题与 §7.1 向导分支小节；指向已删文档的链接替换为 `ARCHITECTURE.md`。
- `dev/AUTO_SYNC.md`：把错位到"本地并发写入配置"节后面的"### Hub 库"挪回"## 同步范围"。

**引用修复（活文档 → `database/` 真实位置）：**
- `dev/CONTRIBUTING.md`：`_row_to_dict` / `_get_conn` / `get_timestamp_with_tz` / `_create_tables` 导入与归属全部改指到 `database.connection` / `database.utils` / `database.schema`。
- `dev/LOGGING_LEVELS.md`：3 处 `_debug_log` 导入改 `database.utils`；补充新/旧两套 logger module key 说明。
- `dev/AUTO_SYNC.md`、`architecture/decision_flow.md`：描述性引用一并指向真实位置。
- 活文档中保留的 `core/db_manager.py` 说明均明确标注为"兼容 facade，新代码请直连 `database/`"。

**删除：**
- `docs/DOCUMENT_INDEX.md`（索引漏列 10+ 文件、维护成本高；AI_CONTEXT + CLAUDE + README 已是 SSoT）。
- `docs/dev/NEW_USER_ZERO_CREDENTIAL_PLAN.md`（5 行纯指针 stub，完整版已在 `history/`）。

**约束精化：**
- `dev/AI_CONTEXT.md` 顶部新增 §0.5 当前状态快照；§0 与 §2 的持久层引用从单一 `core/db_manager.py` 改为 `database/` 5 子模块分层说明。
- `dev/AI_CONTEXT.md §6` 重写：§6.1 影响矩阵分"必改"与"视情况改"；§6.2 拆分 commit 级（py_compile + 红线自查）与 PR 级（pytest + 文档同步）检查；§6.3 新增 CLAUDE.md 与 AI_CONTEXT.md 边界声明（防止双 SSoT 漂移）。

**注**：历史文档中 `history/DOCS_OPTIMIZATION_SUMMARY.md` 与 `history/DOCS_COMPLETION_SUMMARY.md` 里仍引用 `DOCUMENT_INDEX.md`，保留不改（它们是 2026-04-12 的时间胶囊，不应追溯修改）。

## 2026-04-17

### Embedded Replicas 迁移收口（Phase 3/4）
- 同步文档与实现对齐：`sync_databases()` / `sync_hub_databases()` 均采用 `conn.sync()`，旧手工同步辅助函数已移除。
- 更新 `docs/dev/AUTO_SYNC.md` 的进度事件阶段枚举为 `connect|sync|done|error|skipped`，并修正后台日志示例。
- 更新 `README.md`，补充当前同步架构与默认回归测试命令。
- 更新 `docs/dev/QUICK_START.md`，补充最短可执行路径（安装、preflight、测试、运行）。
- 更新 `docs/DOCUMENT_INDEX.md`，纳入 Phase 3/4 文档并刷新时间戳。

### 阶段交付状态对齐
- `docs/dev/EMBEDDED_REPLICAS_PHASE_0_2_COMPLETION.md` 中的“Phase 3/4 可选”改为“已完成”。
- 增加与 `docs/dev/PHASE_3_SYNC_OPTIMIZATION.md`、`docs/dev/PHASE_4_TESTING_VALIDATION.md` 的交叉引用，形成迁移文档闭环。

## 2026-04-14

### CLI 帮助信息增强
- 扩展 `main.py` 的 `--help` 输出，新增完整程序级帮助内容（功能概览、菜单入口、关键环境变量、PowerShell 示例）。
- 保持现有参数兼容：`--env`、`--config`、`--log-level`、`--async-log`、`--enable-stats`。
- 使用 `argparse.RawDescriptionHelpFormatter` 保留多段落帮助格式，提升首次使用可读性。
- 修复 `python main.py --help` 仍触发用户选择的问题：帮助模式下跳过 `config.py` 的交互式 profile 选择。

### AI 批处理可观测性与退出资源释放
- 增强 `main.py` 的批次失败日志：当 AI 批次失败时记录 `batch_index`、`batch_size`、`words`、`latency_ms`、`error`、`error_type` 与失败阶段，便于快速定位是请求异常还是解析异常。
- 增强 `core/mimo_client.py` 的失败元数据：请求重试和 JSON 解析失败都会返回结构化错误信息，并附带关键日志上下文。
- 为 `core/maimemo_api.py` 增加 `close()`，并在 `main.py` 退出 `finally` 中统一调用 AI/MaiMemo 客户端清理入口，减少退出时资源未释放告警风险。

### AI_CONTEXT（Vibe Coding 结构化优化）
- 将 AI 执行规则重构为分级体系：`MUST / SHOULD / NICE-TO-HAVE`，降低执行歧义。
- 新增“变更影响矩阵”，明确代码类型与必须同步文档之间的映射关系。
- 新增“提交前最小检查清单”，统一 AI 与人工收尾标准。
- 新增“反模式（禁止写法）”示例，覆盖同步进度输出、中断处理、compat 导入边界与过期示例问题。
- 将 `AI_CONTEXT.md` 的动态状态说明调整为“状态维护策略”，改为引用 `docs/CHANGELOG.md` 作为状态事实来源。
- 补充跨平台日志命令示例（bash + PowerShell）。

### 用户名大小写语义统一
- 用户名身份语义调整为大小写不敏感：`username.strip().lower()` 作为统一比较与标识基准。
- `generate_user_id()` 改为基于小写用户名生成，避免 `Asher` 与 `asher` 产生不同身份。
- Hub 用户查询改为 `lower(username)` 比较，登录与角色判断统一不区分大小写。
- Profile 加载支持按大小写不敏感解析，旧 profile 文件名大小写不一致时可兼容读取。

### 启动性能优化（同步检查限时）
- 启动一致性检查改为“限时等待 + 后台补偿”：主线程最多等待 `STARTUP_SYNC_CHECK_TIMEOUT_S`（默认 2.5 秒）。
- 超时后先进入主菜单，后台继续完成 dry-run 同步检查并记录结果。
- 后台若检测到本地/云端差异，记录告警并提示用户在菜单中执行同步。

### Hub 初始化提速（状态缓存短路）
- 为 `init_users_hub_tables()` 增加持久化状态缓存，命中有效窗口时直接短路重复 schema 校验。
- Hub 初始化状态记录包含 `hub_fp`、`schema_version` 与 `last_success_at`，用于区分“同库重复启动”与“配置/结构变化”。
- 保留旧式初始化标记兼容，但优先使用状态缓存判断是否需要重新连接与校验。

### 文档治理规则升级
- 强化 `docs/dev/AI_CONTEXT.md` 的硬性规则，新增“代码变更必须同步文档”的完成标准。
- 增加文档更新顺序约束：先规则层（AI_CONTEXT），再专项文档，最后入口文档（README）。
- 补充同步与交互相关约束：
  - 前台同步进度回调与进度显示分层
  - 后台同步静默阶段日志（仅 logger）
  - 输入中断处理统一上抛（避免底层 `print()+sys.exit()`）
  - `compat/` 迁移过渡期导入规范

### Turso API 速查更新
- 重写 `docs/api/turso_api.md`，补充并整理已确认的官方 Turso 接口：组织、用户、位置、组、成员、邀请、数据库、认证令牌、API token、上传迁移与 Turso Sync。
- 明确个人账号的 `organization slug` 与用户名一致，并在速查中标注当前项目的 Turso 双轨使用方式。
- 将 embedded replicas 标记为旧路线，新增当前更推荐的 Turso Sync 说明与项目落点。
- 记录当前镜像范围：核心页面已覆盖，少量官方页面仍以交叉链接形式保留，便于后续继续扩展成逐页全文镜像。
- 新增基于 `sitemap.xml` 的 API Reference 覆盖清单，按路径逐项标记“已镜像/待补”。
- 新增组织计费、审计日志、数据库实例/用量、成员增改、邀请 v2、token list/revoke 等管理侧接口速查。
- 补齐 `introduction` 与 `quickstart` 导读页面镜像，并将 sitemap 覆盖清单更新为 API Reference 全量已镜像状态。

### 同步文档对齐
- 重写 `docs/dev/AUTO_SYNC.md`，对齐当前实现：`progress_callback` 签名、前台进度条与后台阶段日志策略。
- 更新 `docs/dev/CONTRIBUTING.md`，补充 `compat/` 过渡期导入约定与文档影响清单要求。
- 更新 `docs/architecture/LOG_SYSTEM.md`，说明前后台同步日志展示差异。
- 更新 `README.md`，补充 `compat/` 的迁移过渡期说明。

### 文档收口
- 统一 AI 指导入口：`docs/dev/AI_CONTEXT.md` 作为唯一 AI 执行规范来源。
- 精简 `CLAUDE.md` 为高层概览，避免与 AI_CONTEXT 重复维护。
- 更新 `README.md` 与 `DOCUMENT_INDEX.md` 的 AI 指导导航与新手路径描述。

### 历史归档
- 将以下总结型文档迁移到 `docs/history/`：
  - `VIBE_CODING_SUMMARY.md`
  - `DOCS_OPTIMIZATION_SUMMARY.md`
  - `DOCS_COMPLETION_SUMMARY.md`
- 将一次性迁移脚本迁移到 `scripts/archived/`，并补充归档说明。
- 删除明显一次性脚本：`scratch/` 下 3 个校验脚本、`tests/experiments/real_sync_apple.py`。
- 合并日志验证工具入口：移除重复脚本 `tools/verify_logging_integration.py`。

### 新手方案状态
- 更新 `docs/dev/NEW_USER_ZERO_CREDENTIAL_PLAN.md` 状态为已落地版本，并补充实施结果与后续项。
- 新增 `docs/dev/LOGGING.md` 与 `docs/dev/QUICK_START.md` 作为开发导航页。
- 将零凭证新手计划的完整实施记录迁移至 `docs/history/NEW_USER_ZERO_CREDENTIAL_PLAN.md`，`docs/dev/NEW_USER_ZERO_CREDENTIAL_PLAN.md` 仅保留入口。

## 2026-04-12

### 新增文档
- **[DOCUMENT_INDEX.md](DOCUMENT_INDEX.md)**: 文档索引，提供所有文档的快速导航
- **[VIBE_CODING_SUMMARY.md](dev/VIBE_CODING_SUMMARY.md)**: Vibe Coding 优化总结

### 更新文档
- **[OVERVIEW.md](architecture/OVERVIEW.md)**:
  - 更新目录结构，添加 `tools/` 目录
  - 添加 `weak_word_filter.py` 模块说明

- **[AI_CONTEXT.md](dev/AI_CONTEXT.md)**:
  - 添加 `weak_word_filter.py` 模块速查
  - 添加薄弱词筛选规则

- **[CONTRIBUTING.md](dev/CONTRIBUTING.md)**:
  - 添加薄弱词筛选规范
  - 添加评分维度说明

- **[momo_api_summary.md](api/momo_api_summary.md)**:
  - 添加 API 限制处理说明

- **[README.md](../README.md)**:
  - 精简内容，优化格式
  - 添加文档索引链接

### 项目结构优化
- 创建 `tools/` 目录，移动独立工具脚本
- 创建 `CLAUDE.md`，提供 AI 上下文文档
- 创建 `.env.example`，提供环境变量配置模板
- 清理根目录，移除旧日志文件

## 2026-04-11

### 新增功能
- **薄弱词筛选系统** (`weak_word_filter.py`):
  - 多维度评分系统
  - 动态阈值调整
  - 分层筛选策略

### 更新文档
- **[AI_CONTEXT.md](dev/AI_CONTEXT.md)**: 添加当前状态说明
- **[CONTRIBUTING.md](dev/CONTRIBUTING.md)**: 添加开发规范

## 2026-04-10

### 新增文档
- **[AUTO_SYNC.md](dev/AUTO_SYNC.md)**: 自动同步机制说明

### 更新文档
- **[OVERVIEW.md](architecture/OVERVIEW.md)**: 更新架构说明
- **[LOG_SYSTEM.md](architecture/LOG_SYSTEM.md)**: 日志系统设计

---

*文档更新日志由人工维护，记录重要变更。*
