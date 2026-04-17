AI_CONTEXT.md - Momo Study Agent 核心系统上下文与 AI 指令

[系统定位]
你是本项目的高级 Python 协作工程师。任何代码改动前，先读本文件并遵守其中的架构契约。
本文件是 AI 执行规则的唯一事实来源（Single Source of Truth）。

## 0. 新成员先读（3 分钟）

如果你是第一次接触本仓库，请按这个顺序理解系统：

1. `main.py`：主流程编排，负责菜单、任务分发、退出收尾。
2. `core/db_manager.py`：唯一 SQL 写入入口，承接本地持久化和同步状态机。
3. `core/maimemo_api.py`：墨墨 API 封装与限流控制。
4. `docs/dev/AUTO_SYNC.md`：同步链路、前后台边界、退出策略。

目标不是先记住所有细节，而是先抓住三件事：

- 主线程只做“快路径”，网络和重活在后台。
- 数据先落本地再异步上云，任何时刻都要可恢复。
- Hub 库与个人库严格隔离，不混用职责和数据。

## 1. 核心架构与边界

Momo Study Agent 是一个自动化英语学习系统，连接墨墨背单词 OpenAPI 与 LLM（Gemini/Mimo）。

- 主线程（UI）必须保持高响应，仅做读取缓存、调度线程池、入队。
- 持久化采用双轨：SQLite（本地优先）+ Turso（云端备份）。
- 默认将网络写入与云端同步放在后台线程执行；仅用户明确触发的前台同步可例外，但必须有界等待并可超时放行。
- 无网或缺少云端配置时，系统必须可纯本地运行。

## 2. 模块职责图（Module Map）

改动前先确认模块归属，避免越层实现。

- 入口层：`main.py`
  - 职责：流程编排、用户交互、线程池分发、同步收尾。
- 持久层：`core/db_manager.py`
  - 职责：唯一 SQL 写入入口；维护 `sync_status`；处理 SQLite/Turso 双轨行为。
- API 层：`core/maimemo_api.py`
  - 职责：墨墨 OpenAPI 封装；频控、重试、超时和错误归一。
- LLM 层：`core/*_client.py`
  - 职责：模型调用、结果清洗、结构化输出。
- 业务引擎：`core/iteration_manager.py`
  - 职责：重炼/选优链路与薄弱词迭代。
- 基建层：`config.py`, `core/logger.py`
  - 职责：多用户隔离、配置装载、结构化日志。

## 3. MUST 级架构契约（违反即视为严重问题）

### 3.1 数据库与并发

1. Hub 与个人库严格隔离。
    - `TURSO_HUB_DB_URL` 仅用于中央管理/鉴权/统计。
    - `TURSO_DB_URL` 仅用于个人学习数据。
    - 禁止凭据落入个人库，禁止学习记录落入 Hub。
2. 禁用 `row_factory` 依赖。
    - Turso（libsql）不支持 `sqlite3.Row` 语义。
    - 查询结果统一走 `_row_to_dict(cursor, row)`。
3. SQLite 连接必须具备并发兜底。
    - `sqlite3.connect(..., timeout=20.0)`。
    - 执行 `PRAGMA journal_mode=WAL`。
4. 批量写入优先。
    - 禁止在循环中逐条 `INSERT`。
    - 使用 `save_ai_word_notes_batch` 等批量接口。
5. 同步状态机不可破坏。
    - 入队前必须先落库并标记 `sync_status=0`。
    - 后台同步成功后标记 `sync_status=1`。
    - 启动时必须恢复未同步数据（`sync_status=0`）。
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

代码变更必须形成文档闭环。

### 6.1 变更影响矩阵

- 同步逻辑、异步队列、并发策略
  - 必查：`docs/dev/AUTO_SYNC.md`、`README.md`
- 数据库字段、环境变量、用户隔离机制
  - 必查：`docs/dev/QUICK_START.md`、`README.md`
- 系统级规则、反模式、新模块边界
  - 必查：`docs/dev/AI_CONTEXT.md`

### 6.2 提交前检查

- 是否违反 MUST 规则（尤其是 Prompt 外置、Hub/个人库隔离）
- 是否补齐了受影响文档
- 是否使用结构化日志而非 `print()`
- 数据库改动是否具备向后兼容迁移
- 默认回归口径是否通过：`python -m pytest tests/ -v --tb=short -m "not slow"`

## 7. 协作语气与执行期望

在保证规则强度的前提下，协作方式保持清晰、克制、可执行：

- 先给结论，再给证据（文件与函数级定位）。
- 优先最小改动，避免“顺手重构”带来额外风险。
- 对新成员友好：术语统一、路径可追踪、避免只讲抽象原则。
- 如遇规则冲突，以本文件 MUST 条款优先，再回溯到实现和测试。