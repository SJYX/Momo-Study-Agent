# Momo Study Agent 🧠: IELTS AI Vocabulary Expert

[![Python 3.12](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Gemini 2.0/3](https://img.shields.io/badge/AI-Gemini-orange.svg)](https://ai.google.dev/)
[![Mimo AI](https://img.shields.io/badge/AI-Mimo_v2-red.svg)](https://api.xiaomimimo.com/)
[![Maimemo](https://img.shields.io/badge/Sync-Maimemo_API-green.svg)](https://open.maimemo.com/)

**Momo Study Agent** 是一个将“墨墨背单词”开放数据与 Google Gemini 深度大模型结合的自动化英语学习系统。它专门针对 **IELTS (雅思)** 备考流程设计，利用 AI 为你打造全自动的深度词汇分析流。

---

## 🚀 核心特性 (Key Features)

### 1. 🤖 专家级双引擎 AI 分析
- **多模型支持**：原生支持 **Google Gemini** 与 **小米 Mimo (OpenAI 兼容)** 双引擎，可根据需求随时切换。
- **深度处理**：不仅提供释义，还涵盖 **IELTS 考试逻辑**、**高频固定搭配**、**熟词僻义陷阱**。
- **价值评级 (Word Ratings)**：新增 **提分杠杆率 (ROI)**、**学术输出潜力** 与 **易错踩坑指数** 三维评分，帮你精准识别单词学习权重。

### 2. 🛡️ 数据雷达与健壮性
- **持久化存储**：所有 AI 生成的高维度知识图谱全部存储在本地 SQLite 数据库中。
- **自动查重**：每日运行只需处理复习任务中的“新面孔”，已处理过的单词自动跳过，极速提效。
- **异常恢复**：集成 `json-repair` 库，从容应对 AI 输出不规范导致的 JSON 解析异常。

### 3. 🌀 Smart Sync 智能同步系统
- **原生接管**：AI 生成的“核心释义”将直接通过 API 同步。为了保持墨墨 App 界面清爽，同步时会自动剥离 Markdown 标记（加粗、斜体等），仅保留纯文本换行。
- **自动打标**：同步时自动为所有 AI 处理过的单词打上 **“雅思”** 标签。
- **进度可见**：实时打印全局处理进度 `[15/40]`，并清晰展现 AI 消耗的 Token 账单。
- **保护机制**：智能识别已有释义，自动执行覆盖更新而非冲突报错。同时内置 `rollback_interpretations.py` 脚本支持紧急回滚。

---

## 🛠️ 快速上手 (Quick Start)

### 1. 环境准备
确保你的环境中已安装 Python 3.12+，并安装依赖：
```bash
pip install -r requirements.txt
```

### 2. 配置秘钥
在根目录下创建 `.env` 文件，并填写相关 Token：
```env
# 墨墨 OpenAPI Access Token
MOMO_TOKEN="你的_TOKEN"

# Google Gemini API Key (默认使用)
GEMINI_API_KEY="你的_API_KEY"

# 或者使用小米 Mimo API Key (可选)
# MIMO_API_KEY="你的_MIMO_API_KEY"
# AI_PROVIDER=mimo  # 设置为 mimo 时使用小米模型
```

### 3. 开始实战 (Practical Operation)

- **单词实战测试**：
  直接运行实战测试脚本，查看 "apple" 是如何从分析到同步的：
  ```bash
  python tests/experiments/run_full_flow.py
  ```

- **每日全自动同步**：
  运行主程序，全自动拉取今日墨墨任务并进行 AI 升级：
  ```bash
  python main.py
  ```

- **应急回滚 (Rollback)**：
  如果发现推送的内容有误，可以运行脚本将今日处理的所有单词释义重置为精简版：
  ```bash
  python scripts/rollback_interpretations.py
  ```

- **Prompt 效果评估**：
  生成当前 Prompt 对极端多义词的处理报告：
  ```bash
  python tests/generate_evaluation_report.py
  ```

> [!IMPORTANT]
> `main.py` 默认开启 `DRY_RUN = True` 安全模式。在确认逻辑无误后，请将代码中的此开关改为 `False` 以真实写入墨墨及数据库。

---

## 🏗️ 技术栈 (Tech Stack)

- **Python SDK**: `google-genai` (Google 官方最新 SDK)
- **API 通讯**: `requests` + Maimemo OpenAPI v1
- **数据引擎**: `SQLite3` (本地持久化)
- **配置管理**: `python-dotenv`

---

## 💡 工程文档
- [Maimemo API 开发手册](docs/momo_api_summary.md): 整理好的 Maimemo OpenAPI 开发指北。
- [Maimemo OpenAPI 规范](docs/maimemo_openapi.yaml): 官方 OpenAPI (YAML) 完整声明文件。
- [Xiaomi Mimo API 手册](docs/xiaomi_mimo_api.md): 小米 Mimo (OpenAI 兼容) 接口调用指南。
- [Prompt 效果采样报告](docs/prompt_evaluation_sample.md): 针对极端多义词的 AI 解析效果实时预览。

---
*Momo Study Agent - 你的私人雅思考霸备考助手。*