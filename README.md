# Momo Study Agent 🧠: IELTS AI Vocabulary Expert

[![Python 3.12](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Gemini 2.0/3](https://img.shields.io/badge/AI-Gemini_2.0/3-orange.svg)](https://ai.google.dev/)
[![Maimemo](https://img.shields.io/badge/Sync-Maimemo_API-green.svg)](https://open.maimemo.com/)

**Momo Study Agent** 是一个将“墨墨背单词”开放数据与 Google Gemini 深度大模型结合的自动化英语学习系统。它专门针对 **IELTS (雅思)** 备考流程设计，利用 AI 为你打造全自动的深度词汇分析流。

---

## 🚀 核心特性 (Key Features)

### 1. 🤖 IELTS 专家级 AI 分析
- **深度处理**：不仅提供释义，还涵盖 **IELTS 考试逻辑**、**高频固定搭配**、**熟词僻义陷阱** 以及 **写作提分词汇升级**。
- **智能助记**：结合词根词缀、核心逻辑与场景联想，由 `gemini-3-flash` 级引擎直推，生成极具记忆点的知识图谱。

### 2. 🛡️ 本地 SQLite “数据雷达”
- **持久化存储**：所有 AI 生成的高维度知识图谱全部存储在本地 SQLite 数据库中。
- **自动查重**：每日运行只需处理复习任务中的“新面孔”，已处理过的单词自动跳过，极速提效。

### 3. 🌀 Smart Sync 智能同步系统
- **原生接管**：AI 生成的“核心释义”将直接通过 API 同步并覆盖墨墨背单词 App 中的原生释义卡片。
- **自动打标**：同步时自动为所有 AI 处理过的单词打上 **“雅思”** 标签，方便在 App 中分类复习。
- **冲突检测**：智能识别已有释义，自动执行覆盖更新而非冲突报错。

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

# Google Gemini API Key
GEMINI_API_KEY="你的_API_KEY"
```

### 3. 开始实战 (Practical Operation)

- **单词实战测试**：
  直接运行全流程测试脚本，查看 "apple" 是如何从分析到同步的：
  ```bash
  python run_full_flow.py
  ```

- **每日全自动同步**：
  运行主程序，全自动拉取今日墨墨任务并进行 AI 升级：
  ```bash
  python main.py
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
- [Maimemo API 开发手册](file:///c:/Users/112560/OneDrive%20-%20Grundfos/Desktop/Work/Misc/MoMo_Script/momo_api_summary.md): 整理好的 Maimemo OpenAPI 开发指北。

---
*Momo Study Agent - 你的私人雅思考霸备考助手。*