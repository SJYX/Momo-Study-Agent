# Web UI 文档工作区（A+）

更新时间：2026-05-02

## 目录说明

1. `WEB_UI_EXEC_PLAN.md`：主执行计划（总览）
2. `WEB_UI_INTERACTION_PATHS.md`：全量交互路径
3. `WEB_UI_STATUS.yaml`：阶段状态（当前暂不自动更新）
4. `chapters/`：按章节拆分的详细计划书（逐章确认）
5. `archive/`：历史版本或废弃草稿

## 章节推进规则

1. 每次只推进一个章节，先问清需求再落文。
2. 每章文档结构固定：目标、边界、流程、状态机、错误处理、验收、风险、待决问题。
3. 章节确认后：
   - 更新该章节文档
   - 同步更新主计划的对应章节摘要
   - 在 `chapters/CHANGELOG.md` 记录决策

## 当前章节清单

1. C01 首页与导航策略（默认 Ops Monitor）
2. C02 Today Command Center 主闭环
3. C03 失败分组与组级重试
4. C04 TaskDrawer 执行上下文
5. C05 Ops Monitor 监控台
6. C06 Future/Iteration 语义统一
7. C07 Word/Sync/Preflight 二级页统一
8. C08 全局状态机与契约
9. C09 快捷键与效率交互
10. C10 风险控制与确认策略
11. C11 可观测性与埋点
12. C12 验收与发布策略

6. chapters/GLOBAL_TODAY_GUARDRAILS.md：开发全周期 Today 可用性门禁。
7. WEB_UI_EXECUTION_PLAN_V1.md：开发执行计划（批次V1-V5）。
8. V1_TASK_LIST.md：V1（C02+C03）开发任务单。
