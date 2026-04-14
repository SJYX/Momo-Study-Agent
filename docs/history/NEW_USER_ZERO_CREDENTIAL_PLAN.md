# 零凭证新用户上手改造计划

更新时间：2026-04-14
状态：Implemented v1

## 摘要

这份计划记录了零凭证新用户引导的改造目标、实施拆分与验收口径。核心结论已经落地到代码：
- 向导支持“先保存后校验”和“跳过/稍后配置”
- 敏感输入默认隐藏回显
- preflight 提供 text/json 双输出
- FORCE_CLOUD_MODE 冲突支持本次会话临时降级

## 迁移说明

完整实施细节保留在历史档案中，不再作为 dev 目录下的活跃设计文档维护。

## 相关入口

- [docs/dev/AI_CONTEXT.md](../dev/AI_CONTEXT.md)
- [docs/dev/DECISIONS.md](../dev/DECISIONS.md)
- [docs/dev/CONTRIBUTING.md](../dev/CONTRIBUTING.md)
