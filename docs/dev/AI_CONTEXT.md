# AI_CONTEXT.md — Momo Study Agent 上下文速查

> **AI 执行规范唯一来源。** 每次新对话开始时，请先 `@` 引用本文件。

---

## 项目概述

**Momo Study Agent** 是一个将"墨墨背单词"开放数据与 AI 大模型（Gemini/Mimo）深度结合的自动化英语学习系统。

### 核心功能
- **多用户支持**：独立配置和数据隔离，支持一键切换用户
- **AI 助记生成**：支持 Gemini 和 Xiaomi Mimo 模型，生成结构化助记笔记
- **墨墨 API 同步**：自动同步释义、助记、学习计划到墨墨 App
- **智能迭代**：基于多维度评分的薄弱词筛选和优化
- **云端同步**：Turso 云端数据库 + 本地 SQLite 双轨同步

### 技术架构
- **前端**：命令行界面 (CLI)，支持 Windows/Linux/macOS
- **后端**：Python 3.12+，异步日志系统，结构化 JSON 输出
- **数据库**：本地 SQLite + Turso 云端双轨持久化
- **AI 接口**：Google Gemini / Xiaomi Mimo (OpenAI 兼容)

---

## 模块速查表

| 文件 | 职责（一行） |
|------|------------|
| `main.py` | 主菜单编排器，持有 StudyFlowManager，处理 ESC 中断 |
| `config.py` | 路径定义 + 多用户 Profile 加载，所有配置从这里取 |
| `core/maimemo_api.py` | 墨墨 OpenAPI 封装（释义/助记/例句/云词本/学习数据） |
| `core/db_manager.py` | SQLite + Turso 双轨持久化，所有数据库操作走这里 |
| `core/iteration_manager.py` | 薄弱词识别→AI 重炼→推送云词本 的闭环引擎 |
| `core/weak_word_filter.py` | 薄弱词筛选系统（多维度评分、动态阈值、分层筛选） |
| `core/gemini_client.py` | Google Gemini 客户端，暴露 `generate_mnemonics` 接口 |
| `core/mimo_client.py` | 小米 Mimo 客户端，与 Gemini 提供相同接口 |
| `core/logger.py` | 企业级日志系统（JSON 落文件，可读文本到控制台） |
| `core/log_archiver.py` | 日志自动压缩归档 |
| `core/profile_manager.py` | 用户 Profile 目录扫描与选择菜单 |
| `core/config_wizard.py` | 新用户引导向导，含 Token/API Key 联网验证与用户信息记录 |
| `docs/prompts/gem_prompt.md` | 主 AI 生成 Prompt（版本指纹自动归档） |
| `docs/prompts/score_prompt.md` | 迭代打分 Prompt |
| `docs/prompts/refine_prompt.md` | 强力重炼 Prompt |
| `scripts/init_hub.py` | 中央 Hub 数据库初始化工具（表结构 + 管理员创建） |

---

## 执行规则分级（Vibe Coding）

### MUST（违反即为 Bug）

1. 运行时日志必须走 logger；核心业务模块禁止用 `print()` 代替日志（交互式 CLI 提示允许 `print()/input()`）
2. 禁止 `conn.row_factory = sqlite3.Row`（Turso 不支持）；统一使用 `_row_to_dict(cursor, row)`
3. 新增数据库字段只在 `db_manager._create_tables()` 中添加，并用 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 兼容旧库
4. 新增 AI 提供商必须实现 `generate_mnemonics(words, prompt)` 与 `generate_with_instruction(prompt, instruction)`，并在 `main.py` 路由注册
5. 用户数据隔离必须通过 `ACTIVE_USER`，禁止硬编码用户名
6. 用户名身份语义不区分大小写：所有身份比较与 user_id 生成应基于 `username.strip().lower()`
7. Prompt 路径必须从 `config.PROMPT_FILE / SCORE_PROMPT_FILE / REFINE_PROMPT_FILE` 读取
8. 时间字段必须使用含时区的 ISO 8601，调用 `db_manager.get_timestamp_with_tz()`
9. 禁止提交真实凭证；终端输出必须脱敏
10. 首次配置流程保持“先保存后校验”，并通过 `tools/preflight_check.py` 统一体检
11. 薄弱词筛选必须使用 `WeakWordFilter`，不能退化为单阈值筛选
12. 任何影响行为/配置/接口/流程/目录结构的代码改动，必须同轮同步文档
13. 文档更新顺序固定：先本文件（规则层）→ 再专项文档（如 `AUTO_SYNC.md` / `LOGGING.md`）→ 最后 `README.md`
14. 同步回调与显示分层必须保持：
       - 同步函数可接受 `progress_callback: Callable[[Dict[str, Any]], None]`
       - 前台同步由 `main.py` 的 `_run_sync_with_progress()` 显示进度
       - 后台同步由 `_run_sync_with_stage_logs()` 记录阶段日志，不输出进度条
       - `db_manager` 同步函数内部禁止 `print()` 进度
15. compat 为迁移过渡层：
       - 历史 shim 放 `compat/`（如 `compat.gemini_client` / `compat.maimemo_api`）
       - 业务代码只从 `core/` 导入
       - 测试/实验脚本在迁移期可从 `compat/` 导入
16. 输入环节捕获 `KeyboardInterrupt` / `EOFError` 时必须向上抛出，由顶层统一收尾；禁止底层 `print()+sys.exit()`
17. 文档示例中的函数签名、参数、路径必须与当前代码一致
18. 行为已变更但文档未同步，视为未完成实现
19. AI 客户端 JSON 契约：必须强制要求模型直接返回 JSON 数组（`[...]`），严禁包裹在 `{"results": [...]}` 等对象结构中，且必须移除 Markdown 代码块标记（```json）后解析。
20. Maimemo API 同步原则（API 减负）：在生产环境下应优先使用“快路径”，即通过 `force_create=True` 直接尝试 POST 而非先 GET 检查；对于“释义已存在”错误应视为成功，以减少云端 RTT 往返。
21. 线程安全防护：所有涉及全局状态、频控计数或网络 Session 的 API 封装类，必须具备内部 `threading.Lock()` 机制，确保多线程下状态一致性。
22. 批量优先原则：在处理列表数据（如 AI 生成结果）时，必须优先使用 `save_ai_word_notes_batch` 等批量接口，严禁在热路径循环中调用单条写入函数。
23. 同步闭环原则（物理打标）：异步同步任务必须通过数据库状态进行闭环管理。后台线程同步成功后，必须立即调用 `mark_note_synced` 更新 `sync_status = 1`。
24. 断点续传要求：所有具备后台同步能力的 Manager 类，在初始化时必须包含从数据库层面恢复（Resumption）未完成任务的逻辑，确保系统在意外中断后能自动收敛。

### SHOULD（强建议，默认遵循）

1. 在变更说明中附“受影响文档清单”，方便 review 快速核对
2. 对前台/后台行为差异（同步、日志、重试）必须成对描述，避免只写单一路径
3. 新增规范时优先给“可复制模板”，减少 AI 解释误差
4. Hub 初始化应优先命中持久化状态缓存窗口，避免每次启动重复做云端 schema 校验；仅在指纹或 schema 版本变化时回补

### NICE-TO-HAVE（可选增强）

1. 对复杂流程补一段“失败路径”说明（例如同步失败时的降级与收尾）
2. 对高风险改动补一条“为什么不采用替代方案”

## 变更影响矩阵（最小同步集）

| 代码改动类型 | 必须同步文档 |
|---|---|
| 同步逻辑/同步展示改动 | `docs/dev/AUTO_SYNC.md`、`docs/architecture/LOG_SYSTEM.md`、`README.md` |
| 规则或开发约束改动 | `docs/dev/AI_CONTEXT.md`、`docs/dev/CONTRIBUTING.md` |
| 目录结构/导入路径改动 | `README.md`、`docs/DOCUMENT_INDEX.md`、相关专项文档 |
| 新手流程/体检流程改动 | `docs/dev/QUICK_START.md`、`docs/dev/NEW_USER_ZERO_CREDENTIAL_PLAN.md` |

## 提交前最小检查清单

1. 规则是否仍与代码一致（尤其是同步、异常处理、导入约束）
2. 文档示例签名是否与真实函数一致
3. 文档里的路径和文件名是否真实存在
4. 前台与后台行为差异是否都已记录
5. CHANGELOG 是否记录了本轮重要文档策略变化

## 反模式（禁止写法）

1. 在 `db_manager` 同步函数里直接 `print()` 进度
2. 在输入函数底层捕获中断后直接 `print()+sys.exit()`
3. 新业务代码从 `compat/` 导入
4. 改了接口签名但不更新文档示例

---

## 关键架构决策（已否定的方向）

| 否定方案 | 采用方案 | 原因 |
|---------|---------|------|
| `AdvanceStudy` API 强推复习队列 | **云词本 (Notepad) 隔离** | 用户明确要求不打乱每日复习节奏 |
| 纯云端 Turso | **本地 SQLite + Turso 双轨** | 网络抖动时本地继续工作，启动不依赖云端 |
| 逐条 API 请求同步 | **批量/缓存复用** | 减少重复 AI 调用，但仍可能产生云端查询延迟 |
| `get_today_items` 验证 Token | **`get_study_progress` 验证** | 新用户未开课时 today_items 为空会误判 Token 无效 |
| 纯云端中央 Hub | **Turso + 本地 SQLite 回退** | 允许在没有云端凭据时通过本地 Hub.db 进行用户管理与验证 |

---

## 数据流

```
用户 → main.py Menu
         ↓
  MaimemoAPI.get_today_items()
         ↓
  db_manager.is_processed() 过滤
         ↓
  AI Client (Gemini / Mimo) 批量生成
         ↓
  db_manager.save_ai_word_note()
         ↓
  MaimemoAPI.sync_interpretation() / create_note()
         ↓
  db_manager.sync_databases()  ← 本地 ↔ Turso 双向同步
```

---

## 当前状态维护策略

- 本文件聚焦“稳定约束与执行规则”，不承载频繁变化的实施细节。
- 最新状态、阶段性落地结果与文档演进，请以 `docs/CHANGELOG.md` 为准。
- 若某功能状态影响规则判断，应先更新规则，再在 CHANGELOG 记录状态变化。

---

## 日志查阅

```bash
# 查看实时日志（JSON 格式）
cat logs/Asher.log

# 筛选错误
grep "ERROR" logs/Asher.log

# 筛选特定模块
grep '"module": "maimemo_api"' logs/Asher.log
```

```powershell
# Windows PowerShell 查看日志
Get-Content logs/Asher.log

# 筛选错误
Get-Content logs/Asher.log | Select-String "ERROR"

# 筛选特定模块
Get-Content logs/Asher.log | Select-String '"module": "maimemo_api"'
```
