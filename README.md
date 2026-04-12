# Momo Study Agent 🧠

**Momo Study Agent** 是一个将“墨墨背单词”开放数据与 AI 大模型（Gemini/Mimo）深度结合的自动化英语学习系统。

[![Python 3.12](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Gemini 2.0/3](https://img.shields.io/badge/AI-Gemini-orange.svg)](https://ai.google.dev/)
[![Mimo AI](https://img.shields.io/badge/AI-Mimo_v2-red.svg)](https://api.xiaomimimo.com/)
[![Maimemo](https://img.shields.io/badge/Sync-Maimemo_API-green.svg)](https://open.maimemo.com/)

**核心特性**:

- 👥 **多用户支持**：物理隔离配置与数据，一键切换。
- 🏆 **跨用户缓存共享**：自动复用历史 AI 笔记，零成本提速。
- 🗓️ **双模式学习流**：今日任务 + 未来预习。
- 🤖 **专家级 AI 引擎**：支持 Gemini 与 Xiaomi Mimo。
- 🔐 **企业级安全**：Turso 云端同步 + 数据加密。

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

### 5. 🔐 企业级安全与中央管理 (Security & Central Hub)
- **中央 Hub 数据库**：全局 `momo_users_hub` 记录所有用户信息、同步历史与统计数据。支持 **Turso 云端 + 本地 SQLite** 双轨回退。
- **权限安全**：敏感操作（如创建云数据库、管理用户）需验证管理员密码 (`ADMIN_PASSWORD_HASH`)。
- **数据加密**：用户 API 密钥与令牌均经过 **Fernet 对称加密** 存储，杜绝明文风险。

### 6. 🛠️ 工业级运行保障
- **企业级日志系统**：结构化JSON日志、异步处理、性能监控、自动压缩。
- **多环境配置**：支持开发/测试/生产环境，灵活的配置管理。
- **优雅退出**：支持 Windows 环境下 **Esc 键** 快捷退出。
- **自动纠错**：集成 `json-repair` 应对 AI 格式波动，确保数据 100% 入库。

---

## 🛠️ 快速上手

### 1. 安装与启动
```bash
# 安装依赖
pip install -r requirements.txt

# 启动平台
python main.py
```

### 2. 用户初始化

首次运行时，向导会提示输入：

1. **用户名**
2. **墨墨 Access Token**
3. **AI 提供商** (Mimo / Gemini)
4. **API Key**

### 3. 日志系统
支持多环境配置（开发/测试/生产）：

```bash
# 生产环境 (异步 + 压缩)
python main.py --env production

# 开发环境 (调试 + 统计)
python main.py --env development --enable-stats
```

**日志位置**: `logs/<username>.log`

---

## 🏗️ 目录结构

```text
MOMO_Script/
├── main.py                 # 程序入口
├── config.py               # 全局配置与路径
├── core/                   # 核心模块
│   ├── db_manager.py       # 持久化中心（SQLite + Turso 双轨）
│   ├── maimemo_api.py      # MaiMemo OpenAPI 封装
│   ├── iteration_manager.py # 薄弱词智能迭代引擎
│   ├── weak_word_filter.py # 薄弱词筛选系统
│   ├── gemini_client.py    # Google Gemini 客户端
│   ├── mimo_client.py      # 小米 Mimo 客户端
│   ├── logger.py           # 企业级日志
│   ├── profile_manager.py  # 多用户 Profile 管理
│   └── config_wizard.py    # 新用户引导向导
├── data/                   # 运行时数据（gitignore）
│   └── profiles/           # 用户配置 .env
├── docs/                   # 文档体系
│   ├── architecture/       # 系统架构设计
│   ├── api/                # 外部 API 参考文档
│   └── dev/                # 开发者规约
├── tools/                  # 独立工具脚本
├── scripts/                # 维护脚本
├── tests/                  # 测试文件
├── logs/                   # 用户日志（gitignore）
└── CLAUDE.md               # AI 上下文文档
```

---

## 📚 工程文档

### 快速导航

- **[文档索引](docs/DOCUMENT_INDEX.md)** — ⭐ **所有文档的快速导航**
- **[CLAUDE.md](CLAUDE.md)** — ⭐ **AI 开发入口**：项目概览、架构、关键逻辑
- [系统架构概览](docs/architecture/OVERVIEW.md) — 数据流图、模块详解
- [AI 上下文](docs/dev/AI_CONTEXT.md) — 模块速查、硬性规则

### API 参考

- [MaiMemo OpenAPI 规范](docs/api/maimemo_openapi.yaml) — 官方 OpenAPI
- [MaiMemo API 摘要](docs/api/momo_api_summary.md) — 封装调用指北

### 开发指南

- [决策记录](docs/dev/DECISIONS.md) — 已否定方案记录
- [贡献指南](docs/dev/CONTRIBUTING.md) — 开发规约

---
*Momo Study Agent - 你的私人雅思考霸备考助手。*