# 文档更新日志

记录 Momo Study Agent 项目文档的变更历史。

## 2026-04-16

### Prompt 迭代优化系统 (Prompt Iteration & Auditor System)
- **全新 CLI 工具**：新增 `scripts/prompt_dev_tool.py`，支持 `init`, `evaluate`, `optimize`, `loop`, `history`, `accept`, `diff`, `reset`, `clear-eval` 等全生命周期管理。
- **中间解析结果缓存 (Generation Cache)**：实现 `generation_cache` 表，支持 24 小时内的 AI 生成结果自动复用，大幅降低迭代成本与时间。
- **分批审计策略 (Batch Auditing)**：为突破 Mimo/Gemini 的响应时长限制，实现 5 词一包的分批审计逻辑，彻底解决长文本 ReadTimeout 问题。
- **优化器局部重写**：`prompt_optimizer.md` 支持基于审计反馈的“按需更新”，自动冻结已达标模块（得分 >= 9.0），仅针对弱点进行精准微调。
- **迭代可观测性增强**：在终端实时展示分批进度、各模块评分雷达图、详细审计建议。
- **精细化统计**：支持汇总累计 生成 + 审计 的 Token 消耗，并在数据库中记录 `gen_batch_size` 和 `audit_batch_size` 供后期分析。
- **版本回滚与对比**：支持基于 Git 风格的 Prompt 内容回滚，内置彩色 `diff` 命令快速对比生产版与开发版差异。

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
