# Momo Study Agent — AI 会话首页

> 这里是 AI 助手进入项目的**第一页**：拿到地图 / 现状 / 红线摘要 / 调试入口。
> 完整规则（MUST 清单、反模式、数据流）在 [`docs/dev/AI_CONTEXT.md`](docs/dev/AI_CONTEXT.md)——**那才是规则的唯一事实来源**。

## 当前状态（2026-05-28）

- 版本 1.0.0，Python 3.12+，Windows 优先。
- CLI 为主入口（`python main.py`），Web 前端已完成集成（`feat/web-ui` 分支已合并到 main）。启动方式 `python main.py` 或 `python -m web.backend --user <name>`。
- **系统成熟度**：
  - 数据层：主库与 Hub 已切到 `pyturso` 后端，连接管理拆到 `database/connection/` 包；读连接与写单例分流，业务代码不直接建连。
  - 并发层：单写守护线程 + 进程锁稳定；优先队列调度、防饿死保底、多用户活跃追踪已实现。
  - 配置层：profile_loader 三阶段加载、pydantic-settings 模型、Kill Switch 特性开关已上线。
  - Schema 迁移框架已建立，`user_version` 管理和 V001 迁移保留。
  - 代码质量：pre-commit + ESLint 启用，核心路径有持续回归测试覆盖。

> 本页只保留当前会影响开发判断的状态；更完整的历史阶段记录请看 `docs/history/phases/`。

## 模块地图（10 秒扫完）

| 做什么 | 去哪改 | 备注 / 别碰 |
| --- | --- | --- |
| 主流程编排 | `main.py` | 进程锁逻辑动之前必须读 `database/README.md` |
| 业务总线 | `core/study_workflow.py` | 不改公共签名；内部 AI 并发走 `ThreadPoolExecutor` |
| CLI 交互 | `core/ui_manager.py` | 仅 I/O，不要塞业务 |
| 墨墨 API | `core/maimemo_api.py` | 频控 `threading.Lock` 不能去掉 |
| AI 生成 | `core/gemini_client.py` / `core/mimo_client.py` | 复用 `requests.Session` |
| 智能迭代 | `core/iteration_manager.py` + `core/weak_word_filter.py` | 薄弱词必须走多维评分 |
| 同步后台 | `core/sync_manager.py` + `core/sync_priority.py` | PriorityQueue 调度、防饿死保底、闲时引擎 `_is_idle` |
| 活跃 profile | `core/active_profile_registry.py` | 多用户 Web 场景下暂停非活跃 profile 的 P3+ 同步 |
| 运行期指标 | `core/metrics.py` | 进程内 RollingWindow + MetricsCollector（PLAYBOOK B5）；给 B3 闲时引擎与 `/api/ops/metrics` 用 |
| 配置加载 | `config.py` + `core/profile_loader.py` + `core/settings.py` | 三阶段 env + pydantic 模型 |
| 特性开关 | `core/feature_flags.py` | 性能回退时可一键关闭 |
| 数据库读写 | `database/momo_words.py`（业务）、`database/connection/`（连接管理 + 读连接 + 写单例）、`database/execution_engine.py`（写队列 + 同步守护）、`database/schema.py`（表） | **直连 `database/`**；老调用点可通过 `database.legacy` 过渡 |
| Schema 迁移 | `database/migrations/runner.py` + `database/migrations/V001_initial.py` | PRAGMA user_version 管理 |
| 多用户 profile | `core/profile_manager.py` / `core/config_wizard.py` | 凭据永远只写 `data/profiles/<user>.env` |
| 日志 | `core/logger.py` + `core/log_config.py` | 业务层禁 `print()`；使用 throttle 方法避免日志洪泛 |
| 体检 | `tools/preflight_check.py` | 支持 text / json 双输出 |
| Prompts | `docs/prompts/*.md` | 不要硬编码到 Python 字符串 |
| Web 后端 | `web/backend/` | FastAPI ASGI；与 CLI 共享进程锁（互斥） |
| Web 前端 | `web/frontend/` | React + Vite + TypeScript SPA |

## 三条红线（违反即停）

1. **写入必须经写队列**：业务线程严禁直接绕过数据库封装建连或直写；所有写操作通过 `database/execution_engine.py` 的写队列与调度路径提交，由后台守护线程序列化落盘。
2. **Hub 与个人库严格隔离**：`TURSO_HUB_DB_URL` 只装用户元数据/鉴权/审计；`TURSO_DB_URL` 只装学习数据；凭据不落个人库，学习记录不落 Hub。
3. **Prompt 必须外置**：生产 prompt 仍然只放 `docs/prompts/*.md`，由 `config.py` 路径常量读取——禁止在 Python 长字符串里硬编码 prompt。

> 完整 MUST 清单（含游标协议、`row_factory` 禁令、同步状态机、schema 兼容等 6 大节）见 [`docs/dev/AI_CONTEXT.md §3`](docs/dev/AI_CONTEXT.md)。

## 要找东西

- 规则 / 红线全量 → `docs/dev/AI_CONTEXT.md`
- 架构 / 数据流 / 并发模型 / 同步模型 → `docs/architecture/ARCHITECTURE.md`
- 表结构 + sync_status / WordState 状态机 → `docs/architecture/DATABASE_DESIGN.md`
- 启动分支（配置/云端/管理员） → `docs/architecture/decision_flow.md`
- 同步机制（前后台策略、队列、退出收尾） → `docs/dev/AUTO_SYNC.md`
- 运行期 WAL / 游标 / PRAGMA / 重试铁律 → `database/README.md`
- 日志接入 → `docs/dev/LOGGING.md` / `docs/dev/LOGGING_LEVELS.md`
- 代码规范 / 新增 AI 提供商 / 凭证处理 → `docs/dev/CONTRIBUTING.md`
- 设计决策记录（为什么不那样做）→ `docs/dev/DECISIONS.md`
- 快速起步命令 → `docs/dev/QUICK_START.md`
- 当前正在做什么 → `docs/dev/web_ui/README.md`（Web 前端）
- **已完成的历史项目**（不是当前任务！）→ `docs/history/phases/`

## 调试定位

| 想看什么 | 位置 |
| --- | --- |
| 运行日志 | `logs/<user>.log` |
| 个人学习数据库 | `data/history-<user>.db`（+ `.db-wal` / `.db-shm`） |
| Hub 用户数据库 | `data/momo-users-hub.db` 或云端 `TURSO_HUB_DB_URL` |
| 用户凭据 | `data/profiles/<user>.env` |
| 进程锁 | `data/.process.lock`（被占即只能有 1 个 Python 进程在跑） |
| DB 初始化标记 | `data/db_init_markers/` |
| 测试数据库 | `data/test-<user>.db` |

## 常用命令

```bash
# 体检（连通性 + 凭据）
python -m tools.preflight_check --user <username>
python -m tools.preflight_check --user <username> --format json

# 主程序（CLI）
python main.py

# Web 一键启动（生产模式：自动构建前端 → FastAPI 托管）
python scripts/start_web.py
make web

# Web 一键启动（开发模式：后端 + 前端 dev server 并行）
python scripts/start_web.py --dev
make web-dev

# Makefile 快捷
make web          # 生产模式一键启动
make web-dev      # 开发模式一键启动
make web-build    # 仅构建前端
make web-backend  # 仅启动后端（高级用法）

# 默认回归（PR 级）
python -m pytest tests/ -v --tb=short -m "not slow"

# 语法自查（commit 级）
python -m py_compile <你改过的 .py 文件>
```

## 工作守则速记

- 先给结论再给证据（文件与行号）。
- 最小改动，避免"顺手重构"带来回归。
- 改动前确认是否触发 AI_CONTEXT §6.1 的"必改"文档；**只改实现细节不碰文档**。
- 遇规则冲突以 AI_CONTEXT `MUST` 条款为准，再回溯实现和测试。
