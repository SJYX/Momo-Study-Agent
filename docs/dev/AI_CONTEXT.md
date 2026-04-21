AI_CONTEXT.md - Momo Study Agent 核心系统上下文与 AI 指令

[系统定位]
你是本项目的高级 Python 协作工程师。任何代码改动前，先读本文件并遵守其中的架构契约。
本文件是 AI 执行规则的唯一事实来源（Single Source of Truth）。

## 0. 新成员先读（3 分钟）

如果你是第一次接触本仓库，请按这个顺序理解系统：

1. `main.py`：主流程编排，负责菜单、任务分发、退出收尾。
2. `core/study_workflow.py`：业务核心总线（AI 并发、任务过滤、批量落库投递）。
3. `database/connection.py` + `database/momo_words.py`：持久层读写入口（单例连接 + 写队列 + SQL 业务函数）。注：`core/db_manager.py` 是 3972 行兼容 facade，**新代码请直连 `database/` 子模块**。
4. `core/maimemo_api.py`：墨墨 API 封装与限流控制。
5. `docs/dev/AUTO_SYNC.md`：同步链路、前后台边界、退出策略。

目标不是先记住所有细节，而是先抓住三件事：

- 主线程只做“快路径”，网络和重活在后台。
- 数据先落本地再异步上云，任何时刻都要可恢复。
- Hub 库与个人库严格隔离，不混用职责和数据。

## 0.5 当前状态快照

> 本节每次发版或大 PR 合入后更新；`CLAUDE.md` 的「当前状态」以此为准。

- **版本**：1.0.0；Python 3.12+。
- **数据层**：Embedded Replicas 迁移（Phase 0–4）已完成；`conn.sync()` 已取代手工增量同步；`core/db_manager.py` 保留为 3972 行兼容 facade，新代码直接依赖 `database/` 包的 5 个子模块。
- **并发层**：读写分离 + 单写守护线程 + 进程锁已稳定（feat/high-perf-sync 已合回 main）。
- **正在进行**：Web 前端界面初版（`feat/web-ui` 分支，方案见 `docs/dev/WEB_UI_PLAN.md`）。
- **最近变更**：2026-04-21 文档大清理（归档 8 份已完成 PHASE/FIX 文档、architecture 三合一为 `ARCHITECTURE.md`、`CLAUDE.md` 升级为 AI 会话首页）。
- **近期不碰**：`docs/prompts/`（生产 prompt）、`docs/api/`（API 参考）。

## 1. 核心架构与边界

Momo Study Agent 是一个自动化英语学习系统，连接墨墨背单词 OpenAPI 与 LLM（Gemini/Mimo）。

- 主线程（UI）必须保持高响应，仅做读取缓存、调度线程池、入队。
- 持久化采用双轨：SQLite（本地优先）+ Turso（云端备份）。
- 默认将网络写入与云端同步放在后台线程执行；仅用户明确触发的前台同步可例外，但必须有界等待并可超时放行。
- 无网或缺少云端配置时，系统必须可纯本地运行。

## 2. 模块职责图（Module Map）

改动前先确认模块归属，避免越层实现。

- 入口层：`main.py`
  - 职责：全局配置引导与环境拉起，将业务逻辑委派给 `StudyWorkflow`。
- 业务核心：`core/study_workflow.py`
  - 职责：整合本地数据库查询、任务过滤、AI 生成、以及队列消费，提供独立的端到端处理方法。
- 展示层：`core/ui_manager.py`
  - 职责：隔离终端 UI 输入输出交互，统一状态格式呈现。
- 后台同步：`core/sync_manager.py`
  - 职责：高性能后台同步队列维护、墨墨同步网络调度及冲突回写处理。
- 持久层：`database/` 包（**不再是 `core/db_manager.py`**）
  - `database/connection.py`：Embedded Replica 单例连接、写队列、后台写守护线程、后台云同步线程。
  - `database/momo_words.py`：主库业务 SQL（word notes、processed、progress、`sync_databases` / `sync_hub_databases`）。
  - `database/hub_users.py`：Hub 用户业务 SQL。
  - `database/schema.py`：建表与迁移（`_create_tables` / `init_db`）。
  - `database/utils.py`：加密、时间戳、错误分类等底层工具。
  - `core/db_manager.py`：3972 行**兼容 facade**，只为老调用点留命；新代码统一走上面 5 个子模块。
  - 具体运行期铁律（游标协议、自愈、PRAGMA、批量重试）见 [`../../database/README.md`](../../database/README.md)。
- API 层：`core/maimemo_api.py`
  - 职责：墨墨 OpenAPI 封装；频控、重试、超时和错误归一。
- LLM 层：`core/*_client.py`
  - 职责：模型调用、结果清洗、结构化输出。
- 业务引擎：`core/iteration_manager.py`
  - 职责：重炼/选优链路与薄弱词迭代。
- 基建层：`config.py`, `core/logger.py`, `core/log_config.py`
  - 职责：多用户隔离、配置装载、结构化日志配置。

## 3. MUST 级架构契约（违反即视为严重问题）

### 3.1 数据库与并发

1. Hub 与个人库严格隔离。
    - `TURSO_HUB_DB_URL` 仅用于中央管理/鉴权/统计。
    - `TURSO_DB_URL` 仅用于个人学习数据。
    - 禁止凭据落入个人库，禁止学习记录落入 Hub。
2. 禁用 `row_factory` 依赖。
    - Turso（libsql）不支持 `sqlite3.Row` 语义。
    - 查询结果统一走 `_row_to_dict(cursor, row)`。
3. 严禁业务线程直连写库，必须使用读写分离的高并发架构。
    - 读操作：必须使用线程专属的 `_get_thread_local_read_conn()` （防争抢与连接损坏）。
    - 写操作：必须投递给 `_write_queue`（如 `_queue_write_operation`），由后台守护线程单线程序列化执行。禁止业务代码里直接建立普通连接并随意 `INSERT/UPDATE`。
    - 底层仍需执行 `PRAGMA journal_mode=WAL` 和 `timeout=20.0` 作为最终兜底。
4. 批量写入优先。
    - 禁止在交互或循环内部频繁逐条调用写队列模块。
    - 必须使用 `save_ai_word_notes_batch` 等专属聚合接口，借由 `_queue_batch_write_operation` 完成批次事务提交。
5. 同步状态机与内存快路径（Memory-Trust Path）。
    - 常规流水：入队前必须先落库并标记 `sync_status=0`，后台同步成功后标记 `sync_status=1` 或 `2`（冲突）。启动时须恢复未同步数据。
    - 内存兜底豁免：极速模式下允许附加 `force_sync=True` 旗帜直接入网络队列，此时视 AI 返回的实时内存结果为合法，从而跳过入队前“写完再发”的时间差束缚。
6. Schema 变更必须兼容旧库。
    - 在 `_create_tables()` 中维护字段。
    - 使用 `ALTER TABLE ... ADD COLUMN` 做平滑升级。

### 3.2 LLM 与生成

1. Prompt 不得硬编码在 Python 长字符串中。
    - 必须放在 `docs/prompts/*.md` 并由配置路径读取。
2. 生成结果契约为 JSON 数组。
    - 目标格式：`[...]`。
    - 禁止包装为 `{ "results": [...] }`。
3. 解析前必须做 Markdown 清洗。
    - 去掉 ```json 等围栏。
    - 使用 `json_repair.loads()` 处理破损 JSON。
4. 客户端必须复用连接。
    - 在 `__init__` 中初始化 `requests.Session()`。

### 3.3 业务与同步

1. 薄弱词筛选必须走 `WeakWordFilter` 多维策略，禁止退化为单阈值 if。
2. 首次向导遵循“先保存后校验”，云端连通性检查放在 `tools/preflight_check.py`。
3. `maimemo_api.py` 频控逻辑必须有 `threading.Lock()` 保护。
4. 墨墨写入支持 `force_create=True` 快路径；“释义已存在”按成功处理。
5. 所有外部网络请求必须显式 `timeout`（通常 6-12 秒）。
6. 同步主路径必须使用 Embedded Replicas 的 `conn.sync()`；禁止恢复手工逐表增量同步函数模式（如 `_sync_table` 一类实现）。

### 3.4 安全与通用规范

1. 用户身份语义统一为 `username.strip().lower()`。
2. 业务逻辑禁用 `print()`，统一 `self.logger.info/warning/error`。
3. 时间戳统一使用带时区 ISO 8601（`get_timestamp_with_tz()`）。

## 4. 反模式（发现即停）

- 把内存队列当可靠存储，不做 `sync_status` 落盘。
- 在代码里硬编码大段 Prompt，而非外置到文档文件。
- 在底层函数捕获异常后直接 `sys.exit()`，导致上层无法收尾。
- 在底层网络/DB 层输出用户进度 `print("正在同步...")`，而非事件或日志。

## 5. 核心数据流与线程边界

严禁在主线程边界上执行阻塞型网络同步。

```
[主线程]
任务选择 -> 获取词项 -> 本地过滤 -> AI 并发处理
            -> 批量落库(sync_status=0) -> 入同步队列

================= 异步边界 =================

[后台守护线程]
队列消费 -> 墨墨同步(force_create=True) -> 标记 sync_status=1

[退出阶段]
有界等待后台收尾，超时则放行退出（不无限阻塞）
```

## 6. 文档与交付契约

代码变更必须形成文档闭环，但**不是每次改动都要动一堆文档**——按实际影响精准匹配即可。

### 6.1 变更影响矩阵

| 你改了什么 | 必改（行为一致性） | 视情况改（讲清楚为什么） |
| --- | --- | --- |
| 同步逻辑 / 异步队列 / 并发策略 / WAL 配置 | `docs/dev/AUTO_SYNC.md`、`database/README.md` Runtime Iron Rules | `docs/architecture/ARCHITECTURE.md`（图改了才动） |
| 数据库表结构 / 新字段 / 迁移 | `docs/architecture/DATABASE_DESIGN.md` | `docs/architecture/ARCHITECTURE.md`（只影响表时不用动） |
| 环境变量 / 用户 profile 机制 / 凭证 | `.env.example`、`docs/architecture/decision_flow.md` | `README.md`（新手路径变了才动） |
| 系统级规则 / 反模式 / 新模块边界 / 红线 | `docs/dev/AI_CONTEXT.md`（本文件） | `CLAUDE.md`（地图变了才动，规则不搬家） |
| LLM / Prompt 格式 / AI 客户端 | `docs/dev/CONTRIBUTING.md` 的 AI 客户端扩展规范 | `docs/prompts/*.md`（只改版本时不用动规范） |

**改动范围判断法**：如果只是实现细节（比如调整内部函数、加日志、改性能），**不碰文档**；如果改变了"外部可观测行为"（接口、配置、约束、流程），才按上表同步。

### 6.2 检查清单

**Commit 级（每次提交前，1 秒内）：**

- 是否违反 MUST 规则（尤其是 Prompt 外置、Hub/个人库隔离、写队列）
- 是否使用结构化日志而非 `print()`
- 语法 OK：`python -m py_compile <改动文件>`

**PR 级（合并前，30 秒～1 分钟）：**

- 上表中"必改"的文档是否已同步更新
- 数据库改动是否具备向后兼容迁移
- 默认回归口径通过：`python -m pytest tests/ -v --tb=short -m "not slow"`
- 提交信息列出受影响文档清单（评审可追踪）

### 6.3 CLAUDE.md 与 AI_CONTEXT.md 的边界

防止双 SSoT 漂移：

- **CLAUDE.md**（项目根目录）= **AI 会话首页**，只承载"地图、当前状态快照、三条红线摘要、调试入口"。它不保存规则全文。
- **AI_CONTEXT.md**（本文件）= **规则与架构契约的唯一事实来源**。所有 MUST / 反模式 / 数据流边界都在这里。
- CLAUDE.md 的"三条红线"是本文件 §3 的 TL;DR；当 §3 内容有变时，**顺手同步 CLAUDE.md 摘要**。不要在 CLAUDE.md 里新增 AI_CONTEXT 没有的规则。
- AI_CONTEXT §0.5 "当前状态快照"是版本/阶段字段的 SSoT；CLAUDE.md 的当前状态段落从这里同步。

## 7. 协作语气与执行期望

在保证规则强度的前提下，协作方式保持清晰、克制、可执行：

- 先给结论，再给证据（文件与函数级定位）。
- 优先最小改动，避免“顺手重构”带来额外风险。
- 对新成员友好：术语统一、路径可追踪、避免只讲抽象原则。
- 如遇规则冲突，以本文件 MUST 条款优先，再回溯到实现和测试。