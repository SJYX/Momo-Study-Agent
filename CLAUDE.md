# MOMO Script 项目上下文

## 项目概述
这是一个基于墨墨背单词 (Maimemo) OpenAPI 的 AI 助记辅助工具。
核心功能是利用 AI (Mimo/Gemini) 为单词生成助记，并自动同步到墨墨背单词 App。

## 核心架构

### 1. 入口点
- `main.py`: 主程序入口，处理用户交互和主流程控制。

### 2. 核心模块 (`core/`)
- `maimemo_api.py`: 墨墨背单词 API 封装 (处理释义、助记、学习计划同步)。
- `db_manager.py`: 数据库管理 (本地 SQLite + 云端 Turso 同步)。
- `profile_manager.py`: 多用户配置管理。
- `iteration_manager.py`: 智能迭代模块 (优化薄弱词助记)。
- `weak_word_filter.py`: 薄弱词筛选系统 (多维度评分)。
- `mimo_client.py` / `gemini_client.py`: AI 客户端封装。
- `logger.py`: 统一日志系统。

### 3. 配置 (`config/`, `config.py`)
- `config.py`: 全局配置加载 (环境变量、路径定义)。
- `config_wizard.py`: 新用户交互式配置向导。

### 4. 文档 (`docs/`)
- `api/`: 墨墨 API 文档及摘要。
- `architecture/`: 架构图和决策流程。
- `dev/`: 开发指南和上下文。

### 5. 工具与脚本 (`tools/`, `scripts/`)
- `tools/`: 独立的检查、测试脚本 (非核心运行时依赖)。
- `scripts/`: 数据库初始化、回滚等维护脚本。

## 关键运行逻辑

1.  **初始化**:
    - 加载环境变量和用户配置。
    - 初始化数据库 (本地 + 云端)。
    - 选择 AI 提供商 (Mimo/Gemini)。

2.  **主循环** (`main.py` -> `run()`):
    - 获取今日/未来学习任务。
    - **选项 1 (今日任务)**:
        - 检查 `ai_word_notes` 缓存。
        - 未缓存的单词调用 AI 生成助记。
        - 同步助记和释义到墨墨 API。
    - **选项 2 (未来计划)**: 处理未来几天的单词。
    - **选项 3 (智能迭代)**:
        - 使用 `WeakWordFilter` 筛选薄弱词。
        - 分级处理 (Level 0 选优, Level 1+ 重炼)。
        - 同步优化后的助记。
    - **选项 4 (同步&退出)**: 数据同步后退出。

3.  **数据同步**:
    - 程序启动时检查云端差异。
    - 程序退出时自动同步数据到云端 (Turso)。

## 重要注意事项 (Gotchas)

1.  **API 限制**:
    - 墨墨 API 有严格的频率限制 (429 错误) 和创建数量限制 (400 错误)。
    - 代码中已实现重试机制 (`_request`) 和限制检测 (`creation_limit_reached`)。
    - 批处理之间有 3 秒延迟。

2.  **数据库连接**:
    - 使用 `libsql` (Turso) 连接云端。
    - 注意流式协议 (Hrana) 的生命周期，避免在 AI 调用期间持有连接。

3.  **多用户支持**:
    - 通过 `MOMO_USER` 环境变量或启动时交互选择用户。
    - 每个用户有独立的数据库文件 (`data/history-{user}.db`)。

4.  **AI 提供商**:
    - 默认使用 `mimo` (小米)。
    - 可通过 `AI_PROVIDER` 环境变量切换为 `gemini`。

## 开发指南

- **添加新功能**: 优先考虑在 `core/` 模块中实现，保持 `main.py` 简洁。
- **API 调用**: 所有墨墨 API 调用封装在 `MaiMemoAPI` 类中。
- **日志**: 使用 `core.logger` 模块，避免直接使用 `print`。
- **测试**: 新增测试脚本放入 `tools/` 目录。

## 环境变量

参考 `.env.example` (如果存在) 或 `config.py` 中的 `os.getenv` 调用。
关键变量:
- `MOMO_TOKEN`: 墨墨背单词 API Token
- `MIMO_API_KEY` / `GEMINI_API_KEY`: AI API Key
- `TURSO_DB_URL` / `TURSO_AUTH_TOKEN`: 云端数据库配置
