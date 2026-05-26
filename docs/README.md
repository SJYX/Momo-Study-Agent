# 文档总览

本目录采用“活动文档 + 历史归档”双层结构。

## 活动文档（应优先阅读）

- `dev/AI_CONTEXT.md`: AI 与开发协作规则（MUST/反模式/影响矩阵）
- `dev/DEVELOPMENT.md`: 开发导航入口（索引）
- `architecture/ARCHITECTURE.md`: 架构总览
- `architecture/DATABASE_DESIGN.md`: 数据库设计与状态模型
- `dev/AUTO_SYNC.md`: 同步机制说明
- `CHANGELOG.md`: 文档变更历史

## 历史归档（仅供追溯）

- `history/phases/`: 已完成阶段方案与里程碑文档
- `history/snapshots/`: 带日期的一次性状态快照/审查报告
- `history/web_ui_legacy/`: 旧版 Web UI 方案文档

## 归档规则

- 一次性评审、当日总结、阶段完成回顾，不再作为当前开发依据时，应移入 `history/snapshots/`。
- 已被新结构替代的方案文档应移入 `history/phases/` 或 `history/web_ui_legacy/`。
- 活动文档内不保留过时实现描述；历史内容保留在归档中。
