# AI_CONTEXT.md — Momo Study Agent 上下文速查

> **Vibe Coding 入口文件。** 每次新对话开始时，请先 `@` 引用本文件。

---

## 项目概述

一个多用户、跨设备的英语单词助记自动化脚本。通过 MaiMemo OpenAPI 获取每日词汇，调用 AI 模型（Gemini / Xiaomi Mimo）生成结构化助记笔记，写回 MaiMemo App，并用本地 SQLite + 云端 Turso 持久化所有生成数据。

---

## 模块速查表

| 文件 | 职责（一行） |
|------|------------|
| `main.py` | 主菜单编排器，持有 StudyFlowManager，处理 ESC 中断 |
| `config.py` | 路径定义 + 多用户 Profile 加载，所有配置从这里取 |
| `core/maimemo_api.py` | 墨墨 OpenAPI 封装（释义/助记/例句/云词本/学习数据） |
| `core/db_manager.py` | SQLite + Turso 双轨持久化，所有数据库操作走这里 |
| `core/iteration_manager.py` | 薄弱词识别→AI 重炼→推送云词本 的闭环引擎 |
| `core/gemini_client.py` | Google Gemini 客户端，暴露 `generate_mnemonics` 接口 |
| `core/mimo_client.py` | 小米 Mimo 客户端，与 Gemini 提供相同接口 |
| `core/logger.py` | 企业级日志系统（JSON 落文件，可读文本到控制台） |
| `core/log_archiver.py` | 日志自动压缩归档 |
| `core/profile_manager.py` | 用户 Profile 目录扫描与选择菜单 |
| `core/config_wizard.py` | 新用户引导向导，含 Token/API Key 联网验证 |
| `docs/prompts/gem_prompt.md` | 主 AI 生成 Prompt（版本指纹自动归档） |
| `docs/prompts/score_prompt.md` | 迭代打分 Prompt |
| `docs/prompts/refine_prompt.md` | 强力重炼 Prompt |

---

## 硬性规则（违反即为 Bug）

1. **禁止 `print()`**，必须使用 `from core.logger import get_logger; get_logger().info/error(...)`
2. **禁止 `conn.row_factory = sqlite3.Row`**，Turso 连接不支持。用 `_row_to_dict(cursor, row)` 替代
3. **新增数据库字段**：只在 `db_manager._create_tables()` 中添加，并用 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 兼容旧库
4. **新增 AI 提供商**：必须实现 `generate_mnemonics(words, prompt)` + `generate_with_instruction(prompt, instruction)` 两个接口，并在 `main.py` 路由表注册
5. **用户数据隔离**：所有路径通过 `ACTIVE_USER` 区分，禁止硬编码用户名
6. **Prompt 文件路径**：统一从 `config.PROMPT_FILE / SCORE_PROMPT_FILE / REFINE_PROMPT_FILE` 取，不得硬编码

---

## 关键架构决策（已否定的方向）

| 否定方案 | 采用方案 | 原因 |
|---------|---------|------|
| `AdvanceStudy` API 强推复习队列 | **云词本 (Notepad) 隔离** | 用户明确要求不打乱每日复习节奏 |
| 纯云端 Turso | **本地 SQLite + Turso 双轨** | 网络抖动时本地继续工作，启动不依赖云端 |
| 逐条 API 请求同步 | **Batch Chunking（100条/次）** | 消除同步"假死"感，显著降低网络往返延迟 |
| `get_today_items` 验证 Token | **`get_study_progress` 验证** | 新用户未开课时 today_items 为空会误判 Token 无效 |

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

## 当前状态（请 AI 协助更新此节）

- **已完成**：日志系统全量归一化、多设备双轨同步、薄弱词云词本隔离、新用户向导防雷
- **下一步**：文档架构整理（进行中）
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
