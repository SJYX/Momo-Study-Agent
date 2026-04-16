# 文档索引

本文档提供 Momo Study Agent 项目所有文档的快速导航。

## 📚 核心文档

| 文档 | 说明 | 优先级 |
|------|------|--------|
| [AI_CONTEXT.md](dev/AI_CONTEXT.md) | AI 执行规范唯一来源（模块速查、硬性规则、数据流） | ⭐⭐⭐ |
| [LOGGING.md](dev/LOGGING.md) | 开发日志快速参考 | ⭐⭐ |
| [QUICK_START.md](dev/QUICK_START.md) | 开发快速启动 | ⭐⭐ |
| [CLAUDE.md](../CLAUDE.md) | 项目快速上下文（高层概览） | ⭐⭐ |
| [README.md](../README.md) | 项目介绍、快速上手、目录结构 | ⭐⭐⭐ |
| [PROJECT_STATUS.md](../PROJECT_STATUS.md) | 项目状态总结、待办事项、已知问题 | ⭐⭐ |

## 🏗️ 架构设计

| 文档 | 说明 |
|------|------|
| [OVERVIEW.md](architecture/OVERVIEW.md) | 系统架构概览、数据流、模块详解 |
| [decision_flow.md](architecture/decision_flow.md) | 决策流程图、用户初始化流程 |
| [LOG_SYSTEM.md](architecture/LOG_SYSTEM.md) | 日志系统设计、配置说明 |

## 🤖 AI 开发上下文

| 文档 | 说明 |
|------|------|
| [AI_CONTEXT.md](dev/AI_CONTEXT.md) | AI 执行规范唯一来源 |
| [LOGGING.md](dev/LOGGING.md) | 日志接入与排障入口 |
| [QUICK_START.md](dev/QUICK_START.md) | 本地开发起步导航 |
| [DECISIONS.md](dev/DECISIONS.md) | 已否定方案记录 |
| [CONTRIBUTING.md](dev/CONTRIBUTING.md) | 开发规约、代码规范 |
| [NEW_USER_ZERO_CREDENTIAL_PLAN.md](dev/NEW_USER_ZERO_CREDENTIAL_PLAN.md) | 零凭证新用户上手入口（已归档） |

## 🗂️ 历史归档

| 文档 | 说明 |
|------|------|
| [VIBE_CODING_SUMMARY.md](history/VIBE_CODING_SUMMARY.md) | Vibe Coding 优化历史总结 |
| [DOCS_OPTIMIZATION_SUMMARY.md](history/DOCS_OPTIMIZATION_SUMMARY.md) | 文档优化历史记录 |
| [DOCS_COMPLETION_SUMMARY.md](history/DOCS_COMPLETION_SUMMARY.md) | 文档整理完成报告 |

## 🔌 API 参考

| 文档 | 说明 |
|------|------|
| [momo_api_summary.md](api/momo_api_summary.md) | 墨墨 API 开发手册（精简版） |
| [maimemo_openapi.yaml](api/maimemo_openapi.yaml) | 官方 OpenAPI 规范 |
| [xiaomi_mimo_api.md](api/xiaomi_mimo_api.md) | 小米 Mimo API 手册 |
| [turso_api.md](api/turso_api.md) | Turso 数据库 API 说明 |

## 📝 Prompt 文件

| 文件 | 说明 |
|------|------|
| [gem_prompt.md](prompts/gem_prompt.md) | 主 AI 生成 Prompt |
| [score_prompt.md](prompts/score_prompt.md) | 迭代打分 Prompt |
| [refine_prompt.md](prompts/refine_prompt.md) | 强力重炼 Prompt |
| [original_prompt.md](prompts/original_prompt.md) | 原始 Prompt 存档 |
| [system_auditor_prompt.md](prompts/evaluation/system_auditor_prompt.md) | 系统审计器 Prompt（模块化评分） |
| [prompt_optimizer.md](prompts/dev/prompt_optimizer.md) | 提示词优化器 Prompt（局部重写） |
| [sample.md](prompts/evaluation/sample.md) | 审计黄金标准参考样本 |

## 🔧 开发工具

| 文档 | 说明 |
|------|------|
| [AUTO_SYNC.md](dev/AUTO_SYNC.md) | 自动同步机制说明 |
| [PROMPT_OPTIMIZER_PLAN.md](dev/PROMPT_OPTIMIZER_PLAN.md) | Prompt 迭代优化系统实施计划 |

## 📖 快速查找指南

### 如果你是新开发者
1. 阅读 [CLAUDE.md](../CLAUDE.md) 了解项目概览
2. 查看 [AI_CONTEXT.md](dev/AI_CONTEXT.md) 了解执行规范与模块职责
3. 参考 [LOGGING.md](dev/LOGGING.md) 和 [CONTRIBUTING.md](dev/CONTRIBUTING.md) 了解开发规范

### 如果你要修改代码
1. 查看 [OVERVIEW.md](architecture/OVERVIEW.md) 了解架构
2. 参考 [AI_CONTEXT.md](dev/AI_CONTEXT.md) 的硬性规则（唯一规范源）
3. 阅读 [LOGGING.md](dev/LOGGING.md) 和 [CONTRIBUTING.md](dev/CONTRIBUTING.md) 的代码规范

### 如果你要调试问题
1. 查看 [LOG_SYSTEM.md](architecture/LOG_SYSTEM.md) 了解日志系统
2. 参考 [AI_CONTEXT.md](dev/AI_CONTEXT.md) 的数据流说明
3. 阅读 [DECISIONS.md](dev/DECISIONS.md) 了解已否定方案
4. 需要同步行为说明时查看 [AUTO_SYNC.md](dev/AUTO_SYNC.md)

### 如果你要扩展 API
1. 阅读 [momo_api_summary.md](api/momo_api_summary.md) 了解 API 结构
2. 查看 [maimemo_openapi.yaml](api/maimemo_openapi.yaml) 了解详细规范
3. 参考 [CONTRIBUTING.md](dev/CONTRIBUTING.md) 的 AI 客户端扩展规范

---

*文档更新时间：2026-04-16*
