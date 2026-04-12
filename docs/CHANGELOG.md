# 文档更新日志

记录 Momo Study Agent 项目文档的变更历史。

## 2026-04-12

### 新增文档
- **[DOCUMENT_INDEX.md](DOCUMENT_INDEX.md)**: 文档索引，提供所有文档的快速导航
- **[VIBE_CODING_SUMMARY.md](dev/VIBE_CODING_SUMMARY.md)**: Vibe Coding 优化总结

### 更新文档
- **[OVERVIEW.md](architecture/OVERVIEW.md)**:
  - 更新目录结构，添加 `tools/` 目录
  - 添加 `weak_word_filter.py` 模块说明

- **[AI_CONTEXT.md](dev/AI_CONTEXT.md)**:
  - 添加 `weak_word_filter.py` 模块速查
  - 添加薄弱词筛选规则

- **[CONTRIBUTING.md](dev/CONTRIBUTING.md)**:
  - 添加薄弱词筛选规范
  - 添加评分维度说明

- **[momo_api_summary.md](api/momo_api_summary.md)**:
  - 添加 API 限制处理说明

- **[README.md](../README.md)**:
  - 精简内容，优化格式
  - 添加文档索引链接

### 项目结构优化
- 创建 `tools/` 目录，移动独立工具脚本
- 创建 `CLAUDE.md`，提供 AI 上下文文档
- 创建 `.env.example`，提供环境变量配置模板
- 清理根目录，移除旧日志文件

## 2026-04-11

### 新增功能
- **薄弱词筛选系统** (`weak_word_filter.py`):
  - 多维度评分系统
  - 动态阈值调整
  - 分层筛选策略

### 更新文档
- **[AI_CONTEXT.md](dev/AI_CONTEXT.md)**: 添加当前状态说明
- **[CONTRIBUTING.md](dev/CONTRIBUTING.md)**: 添加开发规范

## 2026-04-10

### 新增文档
- **[AUTO_SYNC.md](dev/AUTO_SYNC.md)**: 自动同步机制说明

### 更新文档
- **[OVERVIEW.md](architecture/OVERVIEW.md)**: 更新架构说明
- **[LOG_SYSTEM.md](architecture/LOG_SYSTEM.md)**: 日志系统设计

---

*文档更新日志由人工维护，记录重要变更。*
