# Momo Study Agent — AI 会话首页

> 这里是 AI 助手进入项目的**第一页**：拿到地图 / 现状 / 红线摘要 / 调试入口。
> 完整规则（MUST 清单、反模式、数据流）在 [`docs/dev/AI_CONTEXT.md`](docs/dev/AI_CONTEXT.md)——**那才是规则的唯一事实来源**。

## 当前状态（2026-04-21）

- 版本 1.0.0，Python 3.12+，Windows 优先。
- CLI 为主入口（`python main.py`），Web 前端初版在 `feat/web-ui` 分支（方案见 `docs/dev/WEB_UI_PLAN.md`）。
- 数据层：Embedded Replicas 迁移已完成（Phase 0–4），`conn.sync()` 取代手工增量；持久逻辑拆到 `database/` 包。
- 并发层：单写守护线程 + 进程锁稳定（feat/high-perf-sync 已合回 main）。
- 近期完成：2026-04-21 文档大清理（归档已完成 PHASE 文档、architecture 三合一）。

> 版本与阶段字段的 SSoT 是 `docs/dev/AI_CONTEXT.md §0.5`；本段与其保持同步。

## 模块地图（10 秒扫完）

| 做什么 | 去哪改 | 备注 / 别碰 |
| --- | --- | --- |
| 主流程编排 | `main.py` | 进程锁逻辑动之前必须读 `database/README.md` |
| 业务总线 | `core/study_workflow.py` | 不改公共签名；内部 AI 并发走 `ThreadPoolExecutor` |
| CLI 交互 | `core/ui_manager.py` | 仅 I/O，不要塞业务 |
| 墨墨 API | `core/maimemo_api.py` | 频控 `threading.Lock` 不能去掉 |
| AI 生成 | `core/gemini_client.py` / `core/mimo_client.py` | 复用 `requests.Session` |
| 智能迭代 | `core/iteration_manager.py` + `core/weak_word_filter.py` | 薄弱词必须走多维评分 |
| 同步后台 | `core/sync_manager.py` | 墨墨释义同步队列 |
| 数据库读写 | `database/momo_words.py`（业务）、`database/connection.py`（连接+写队列+同步守护）、`database/schema.py`（表） | **直连 `database/`**；老调用点可通过 `database.legacy` 过渡 |
| 配置加载 | `config.py` | `ACTIVE_USER` 是**模块级全局**，改动影响面大 |
| 多用户 profile | `core/profile_manager.py` / `core/config_wizard.py` | 凭据永远只写 `data/profiles/<user>.env` |
| 日志 | `core/logger.py` + `core/log_config.py` | 业务层禁 `print()` |
| 体检 | `tools/preflight_check.py` | 支持 text / json 双输出 |
| Prompts | `docs/prompts/*.md` | 不要硬编码到 Python 字符串 |

## 三条红线（违反即停）

1. **写入必须经写队列**：业务线程严禁直接调 `libsql.connect` 或 `INSERT/UPDATE`；所有写操作通过 `database/connection.py` 的 `_write_queue`/`_queue_write_operation` 投递，由后台守护线程序列化落盘。
2. **Hub 与个人库严格隔离**：`TURSO_HUB_DB_URL` 只装用户元数据/鉴权/审计；`TURSO_DB_URL` 只装学习数据；凭据不落个人库，学习记录不落 Hub。
3. **Prompt 必须外置**：生产 prompt 只能放 `docs/prompts/*.md`，由 `config.py` 路径常量读取——禁止在 Python 长字符串里硬编码 prompt。

> 完整 MUST 清单（含游标协议、`row_factory` 禁令、同步状态机、schema 兼容等 6 大节）见 [`docs/dev/AI_CONTEXT.md §3`](docs/dev/AI_CONTEXT.md)。

## 要找东西

- 规则 / 红线全量 → `docs/dev/AI_CONTEXT.md`
- 架构 / 数据流 / 并发模型 / 同步模型 → `docs/architecture/ARCHITECTURE.md`
- 表结构 + sync_status 三态 → `docs/architecture/DATABASE_DESIGN.md`
- 启动分支（配置/云端/管理员） → `docs/architecture/decision_flow.md`
- 同步机制（前后台策略、队列、退出收尾） → `docs/dev/AUTO_SYNC.md`
- 运行期 WAL / 游标 / PRAGMA / 重试铁律 → `database/README.md`
- 日志接入 → `docs/dev/LOGGING.md` / `docs/dev/LOGGING_LEVELS.md`
- 代码规范 / 新增 AI 提供商 / 凭证处理 → `docs/dev/CONTRIBUTING.md`
- 设计决策记录（为什么不那样做）→ `docs/dev/DECISIONS.md`
- 快速起步命令 → `docs/dev/QUICK_START.md`
- 当前正在做什么 → `docs/dev/WEB_UI_PLAN.md`（Web 前端）
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

# 主程序
python main.py

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
