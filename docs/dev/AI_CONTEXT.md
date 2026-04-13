# AI_CONTEXT.md — Momo Study Agent 上下文速查

> **Vibe Coding 入口文件。** 每次新对话开始时，请先 `@` 引用本文件。

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

## 硬性规则（违反即为 Bug）

1. **禁止 `print()`**，必须使用 `from core.logger import get_logger; get_logger().info/error(...)`
2. **禁止 `conn.row_factory = sqlite3.Row`**，Turso 连接不支持。用 `_row_to_dict(cursor, row)` 替代
3. **新增数据库字段**：只在 `db_manager._create_tables()` 中添加，并用 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 兼容旧库
4. **新增 AI 提供商**：必须实现 `generate_mnemonics(words, prompt)` + `generate_with_instruction(prompt, instruction)` 两个接口，并在 `main.py` 路由表注册
5. **用户数据隔离**：所有路径通过 `ACTIVE_USER` 区分，禁止硬编码用户名
6. **Prompt 文件路径**：统一从 `config.PROMPT_FILE / SCORE_PROMPT_FILE / REFINE_PROMPT_FILE` 取，不得硬编码
7. **时间戳格式**：所有数据库时间字段使用 ISO 8601 含时区格式，调用 `db_manager.get_timestamp_with_tz()`
8. **凭证管理**：开源版本由用户自行在 `.env` 或 profile 中维护凭证；禁止将真实凭证提交到仓库
9. **薄弱词筛选**：使用 `WeakWordFilter` 类进行多维度评分，而非单一阈值

---

## 关键架构决策（已否定的方向）

| 否定方案 | 采用方案 | 原因 |
|---------|---------|------|
| `AdvanceStudy` API 强推复习队列 | **云词本 (Notepad) 隔离** | 用户明确要求不打乱每日复习节奏 |
| 纯云端 Turso | **本地 SQLite + Turso 双轨** | 网络抖动时本地继续工作，启动不依赖云端 |
| 逐条 API 请求同步 | **Batch Chunking（100条/次）** | 消除同步"假死"感，显著降低网络往返延迟 |
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

## 当前状态

- **已完成**：
  - 日志系统全量归一化、多设备双轨同步、薄弱词云词本隔离、新用户向导防雷
       - 新用户可选 Turso 云数据库创建
  - 中央用户信息库（momo-users-hub）已完成云端建立并支持双轨：
    - 逻辑：优先 Turso，无配置则自动回退至 `data/momo-users-hub.db`
    - 表结构：users, user_api_keys, user_sync_history, user_stats, user_sessions, admin_logs
    - 鉴权：集成 **Token 自提升逻辑**，使用专用 `momo-hub-manager` 令牌
       - 开源凭证模式上线：用户自配 `TURSO_MGMT_TOKEN`、`TURSO_ORG_SLUG` 与 AI Key
  - 用户会话自动跟踪（startup 记录，支持后续 logout 更新）
  - 全局时区感知（ISO 8601 格式 + UTC 时区偏移）
- **已知限制**：智能迭代功能（选项 3）依赖 `word_progress_history` 有足够的历史快照才能触发，新库首次运行可能无薄弱词

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
