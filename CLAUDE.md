# MOMO Script 快速上下文

本文件用于提供项目高层概览。

## AI 协作入口

AI 开发与改动执行规范请统一参考：
- `docs/dev/AI_CONTEXT.md`

`AI_CONTEXT.md` 是当前唯一的 AI 执行规范来源；本文件不再重复维护硬性规则。

## 项目概述

MOMO Script 是一个基于墨墨背单词 OpenAPI 的 AI 助记工具，支持多用户、AI 生成助记、云端同步与智能迭代。

## 核心路径

1. `main.py`：主流程入口与菜单编排
2. `config.py`：配置加载与用户 profile 初始化
3. `core/`：API、数据库、AI 客户端、日志、迭代引擎
4. `tools/preflight_check.py`：首次运行前体检与修复提示

## 关键目录

- `core/`：业务核心模块
- `docs/`：文档体系（架构/API/开发）
- `tools/`：诊断与辅助工具
- `scripts/`：维护脚本
- `tests/`：测试集

## 封版备注

- 首次向导已支持“先保存后校验”与“可跳过”。
- preflight 已支持 text/json 双输出。
- 强制云端冲突时支持本次会话临时降级。
