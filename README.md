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

---

## 🏗️ 目录结构

```text
E:\MOMO_Script/
├── core/                # 核心处理包
│   ├── config_wizard.py # 交互式向导
│   ├── db_manager.py    # 跨库查重与持久化
│   ├── logger.py        # 日志核心
│   ├── log_config.py    # 日志配置管理
│   ├── log_archiver.py  # 日志压缩归档
│   └── maimemo_api.py   # SDK 封装
├── config/              # 配置文件
│   └── logging.yaml     # 日志系统配置
├── data/                # 用户数据区
│   ├── profiles/        # 各用户独立配置 (.env)
│   └── history_*.db     # 各用户学习记录
├── logs/                # 增量日志 (自动轮转压缩)
├── tests/               # 测试用例
└── main.py              # 程序总入口
```

---

## 💡 工程文档
- [系统架构与设计全解](docs/TECHNICAL_DETAILS.md): 深入了解每个模块的设计思路、模式与架构。
- [日志系统优化总结](docs/LOGGING_OPTIMIZATION_SUMMARY.md): 日志系统的完整优化历程和使用指南。
- [Maimemo API 开发手册](docs/momo_api_summary.md): 整理好的 Maimemo OpenAPI 开发指北。
- [Maimemo OpenAPI 规范](docs/maimemo_openapi.yaml): 官方 OpenAPI (YAML) 完整声明文件。
- [Xiaomi Mimo API 手册](docs/xiaomi_mimo_api.md): 小米 Mimo (OpenAI 兼容) 接口调用指南。

---
*Momo Study Agent - 你的私人雅思考霸备考助手。*