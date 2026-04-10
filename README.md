# Momo Study Agent 🧠: Multi-User AI Vocabulary Platform

[![Python 3.12](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Gemini 2.0/3](https://img.shields.io/badge/AI-Gemini-orange.svg)](https://ai.google.dev/)
[![Mimo AI](https://img.shields.io/badge/AI-Mimo_v2-red.svg)](https://api.xiaomimimo.com/)
[![Maimemo](https://img.shields.io/badge/Sync-Maimemo_API-green.svg)](https://open.maimemo.com/)

**Momo Study Agent** 是一个将“墨墨背单词”开放数据与 AI 大模型（Gemini/Mimo）深度结合的自动化英语学习系统。它现已进化为支持**多用户并行**、**跨用户缓存共享**的企业级备考辅助平台。

---

## 🚀 核心特性 (Key Features)

### 1. 👥 多用户 Profile 体系 (Multi-User Architecture)
- **物理隔离**：每个用户拥有独立的 `.env` 配置文件与 `.db` 数据库。
- **一键切换**：启动时自动显示用户菜单，支持快速切换或创建新用户。
- **交互向导**：内置配置向导，支持在输入 Token 后立即进行**联网校验**，确保配置即刻生效。

### 2. 🏆 跨用户“零成本”共享缓存 (Community Cache)
- **极速提效**：自动搜索本地所有用户的历史库。
- **数据复用**：如果用户 A 处理过某个词，用户 B 遇到该词时将直接复用 A 的 AI 笔记，**Token 消耗为 0**，同步速度提升 10 倍。

### 3. 🗓️ 双模式学习流 (Dual-Mode Flow)
- **今日任务**：处理当日待学/复习的动态计划。
- **未来预习**：自主选择未来 N 天（如 3-7 天）即将到来的单词进行超前解析，备考更从容。

### 4. 🤖 专家级 AI 分析引擎
- **多模型支持**：原生支持 **Google Gemini** 与 **小米 Mimo (OpenAI 兼容)**。
- **高阶知识图谱**：精准识别 IELTS 考试逻辑、熟词僻义、搭配陷阱与提分杠杆率。

### 5. 🛠️ 工业级运行保障
- **企业级日志系统**：结构化JSON日志、异步处理、性能监控、自动压缩。
- **多环境配置**：支持开发/测试/生产环境，灵活的配置管理。
- **详细日志**：在 `logs/` 目录下按用户名生成带时间戳的增量日志文件。
- **优雅退出**：支持 Windows 环境下 **Esc 键** 快捷退出。
- **自动纠错**：集成 `json-repair` 应对 AI 格式波动，确保数据 100% 入库。

---

## 🛠️ 快速上手 (Quick Start)

### 1. 安装环境
```bash
pip install -r requirements.txt
```

### 2. 启动平台
直接运行主程序，即可进入用户管理与学习模式选择：
```bash
python main.py
```

### 3. 日志系统配置 (Logging System)
Momo Study Agent 配备了企业级的日志系统，支持多环境配置、性能监控和自动压缩。

#### 基本使用
```bash
# 默认开发环境
python main.py

# 生产环境 (异步日志 + 压缩)
python main.py --env production

# Staging环境 (带统计功能)
python main.py --env staging --enable-stats

# 自定义配置
python main.py --env development --config config/custom_logging.yaml --async-log
```

#### 环境变量配置
```bash
# 设置环境
export MOMO_ENV=production
export MOMO_CONFIG_FILE=config/prod_logging.yaml

# 运行程序
python main.py
```

#### 环境配置说明
- **development**: 调试级别日志，同步写入，启用统计
- **staging**: 信息级别日志，异步写入，启用统计和压缩
- **production**: 警告级别日志，异步写入，启用压缩，禁用统计

#### 高级功能
```python
# 在代码中使用日志系统
from core.logger import setup_logger

# 创建带性能监控的日志器
logger = setup_logger("username", environment="production", enable_stats=True)

# 性能监控装饰器
@logger.log_performance
def my_function():
    # 你的代码
    pass

# 查看统计信息
stats = logger.get_statistics()
print(f"总日志数: {stats['total_logs']}")
```

#### 日志文件位置
- **开发环境**: `logs/username.log`
- **生产环境**: `logs/username.log` (自动压缩为 `.gz` 文件)
- **统计报告**: 实时显示在控制台

### 4. 用户初始化
如果是首次运行，请根据屏幕提示输入：
1.  **用户名** (如 Asher)
2.  **墨墨 Access Token**
3.  **AI 提供商选择** (Mimo 或 Gemini)
4.  **API Key**
向导会自动完成连通性测试并为您创建 Profile。

### 5. 底层模块全量接管 (Comprehensive Logging)
所有底层核心引擎（包括 `db_manager`, `maimemo_api`, `mimo_client`, `log_archiver` 等）已彻底剥离控制台硬编码的 `print` 输出。这带来了以下核心优势：
- **终端免打扰**：主菜单运行过程中不再被零碎的 API Error 或同步细节打断，保持清爽。
- **排错无死角**：JSON 解析失败、双向同步细节和 API 连接超时等所有边缘 Case，全部会被安全收集到了 `logs/<用户名>.log` JSON 中，便于未来的检索与追溯。

---

## 🏗️ 目录结构

```text
MOMO_Script/
├── main.py              # 程序入口
├── config.py            # 全局配置与路径
├── core/                # 核心模块
│   ├── db_manager.py    # 持久化中心（SQLite + Turso 双轨）
│   ├── maimemo_api.py   # MaiMemo OpenAPI 封装
│   ├── iteration_manager.py  # 薄弱词智能迭代引擎
│   ├── gemini_client.py # Google Gemini 客户端
│   ├── mimo_client.py   # 小米 Mimo 客户端
│   ├── logger.py        # 企业级日志（JSON落文件+可读控制台）
│   ├── log_archiver.py  # 日志自动压缩归档
│   ├── profile_manager.py   # 多用户 Profile 管理
│   └── config_wizard.py     # 新用户引导向导
├── data/                # 运行时数据（gitignore）
│   ├── profiles/        # 用户配置 .env
│   └── prompts/         # Prompt 历史版本归档
├── docs/                # 文档体系
│   ├── architecture/    # 系统架构设计
│   ├── api/             # 外部 API 参考文档
│   ├── prompts/         # Prompt 源文件
│   ├── guides/          # 操作指南
│   └── dev/             # 开发者规约（Vibe Coding 入口）
├── logs/                # 用户日志（gitignore）
├── tests/               # 测试文件
└── scripts/             # 工具脚本
```

---

## 📚 工程文档

### 架构
- [系统架构概览](docs/architecture/OVERVIEW.md) — 数据流图、模块详解、核心设计模式
- [日志系统设计](docs/architecture/LOG_SYSTEM.md) — 日志配置、格式规范、运维指南

### API 参考
- [MaiMemo OpenAPI 规范](docs/api/maimemo_openapi.yaml) — 官方 OpenAPI YAML
- [MaiMemo API 开发手册](docs/api/momo_api_summary.md) — 封装调用指北
- [Xiaomi Mimo API 手册](docs/api/xiaomi_mimo_api.md) — OpenAI 兼容接口说明

### Vibe Coding（AI 开发入口）
- [**AI_CONTEXT.md**](docs/dev/AI_CONTEXT.md) — ⭐ **每次新对话先读这个**：模块速查、硬性规则、数据流
- [DECISIONS.md](docs/dev/DECISIONS.md) — 已否定方案记录，防止重蹈覆辙
- [CONTRIBUTING.md](docs/dev/CONTRIBUTING.md) — 开发规约：日志、数据库、AI 接口扩展

---
*Momo Study Agent - 你的私人雅思考霸备考助手。*