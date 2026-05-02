# V1 任务单（C02 + C03）

更新时间：2026-05-02（v2 修订：插入 T0、拆分 T6、明确文件边界与门禁口径）
目标：不影响日常 Today 使用前提下，落地 Today 主闭环与失败分组重试
范围：仅任务拆分，不执行代码修改

---

## 0. 输入文档

1. `docs/dev/web_ui/WEB_UI_EXEC_PLAN.md`
2. `docs/dev/web_ui/WEB_UI_EXECUTION_PLAN_V1.md`
3. `docs/dev/web_ui/chapters/C02_TODAY_COMMAND_CENTER.md`
4. `docs/dev/web_ui/chapters/C03_FAILURE_GROUPS_AND_RETRY.md`
5. `docs/dev/web_ui/chapters/GLOBAL_TODAY_GUARDRAILS.md`

---

## 0.1 v2 修订说明

v1 任务单存在 5 处落地阻塞：

1. 缺 feature flag 体系（T9 立项前任何 T1-T8 都没法 behind flag）
2. 缺组级重试后端入口（T6 前端无 API 可用）
3. 缺 error_type/error_code 协议字段（T5 分组无稳定键）
4. 没有"Today 冒烟 E2E"实测用例（T10 门禁口径无法判定）
5. A/B 组并行会撞 `TodayTasks.tsx` 单文件

v2 修订：

1. 插入 T0 作为前置任务，含 flag 骨架 + RowState 协议扩展
2. T6 拆分为 T6a（后端入口）+ T6b（前端动作）
3. 明确文件边界（A 组 / B 组各自独立目录）
4. 门禁口径定为 (a) 后端 pytest + (b) 前端 Vitest 纯函数单测
5. 列出 V1 近似实现项与延期到 C08 的契约升级项

---

## 1. V1 验收口径（完成定义）

V1 完成必须同时满足：

1. Today 默认行为：行视图优先 + 默认仅可执行项
2. 执行链路可用：轻确认条 -> 执行 -> 跟随当前行 -> 完成停留摘要
3. 失败闭环可用：失败分组 -> 组级重试 -> >100 条二次确认 -> 失败残留高亮
4. 不影响日常使用：全局门禁通过（pytest tests/web/ + 前端 Vitest + build/typecheck）
5. 支持快速回退：新增交互受 feature flag 控制，提供一键全关回退

---

## 2. 文件边界（强制，避免 A/B 组冲突）

| 组 | 边界范围 | 备注 |
| --- | --- | --- |
| 公共 | `web/frontend/src/utils/featureFlags.ts` | T0 创建，T9 收口 |
| 公共 | `web/backend/schemas.py` + `web/frontend/src/api/types.ts` | T0/T6a 各自扩展不同字段，避免重叠 |
| A 组 | `web/frontend/src/pages/TodayTasks.tsx`（外壳） | A 组独占。挂点为 B 组面板预留 props，由 A 组负责挂载 |
| A 组 | `web/frontend/src/components/today/LightConfirmBar.tsx`（新） | T2 |
| A 组 | `web/frontend/src/components/today/SummaryPanel.tsx`（新） | T4 |
| A 组 | `web/frontend/src/utils/todayView.ts`（新，纯函数） | T1/T3 筛选/排序/跟随逻辑 |
| B 组 | `web/frontend/src/components/today/FailureGroupsPanel.tsx`（新） | T5/T6b/T7/T8 |
| B 组 | `web/frontend/src/utils/failureGrouping.ts`（新，纯函数） | T5 分组算法 |
| B 组 | `web/backend/routers/study.py` + 相关测试 | T6a |

并行约束：

1. T0 必须先单独落地，A/B 组都依赖 flag 工具与协议字段
2. A 组 T1-T4 与 B 组 T5/T8 可在 T0 完成后并行
3. T6a 后端入口落地后 T6b 才能动
4. T9/T10 串行收尾

---

## 3. V1 近似实现声明

以下行为在 V1 用近似实现，正式契约升级排到 C08：

| 项 | V1 近似 | 正式契约（延期） |
| --- | --- | --- |
| "可执行项"筛选 | `phase != 'skipped' && status != 'done'`，事件未到达视为可执行 | TodayItem 增加 `executable: bool` 字段 |
| "价值优先"排序 | `familiarity_short ASC, review_count DESC` | TodayItem 增加 `value_score: float` 字段 |
| "时间压力"次级排序 | 沿用 `review_count DESC` 作为代理 | 引入显式截止字段 |
| `error_type`/`error_code` | 后端先留空字段，前端 fallback 用 `phase` 兜底 | 后端 workflow 改造，发射结构化错误码 |
| 自动跟随行 | 跟随首个 `status==='running'` 的行 | 多并发 running 时的优先级策略 |

---

## 4. 任务拆分（v2 修订版）

## T0. Feature flag 骨架 + 类型契约扩展（前置）

目标：先把 flag 工具与协议字段铺好，避免后续任务回头改协议。

产出：

1. `web/frontend/src/utils/featureFlags.ts`：env（`VITE_FF_*`） + URL（`?ff_xxx=on`） + localStorage（`ff_xxx`）三层覆盖；提供 `isEnabled(key)` 与 `disableAll()`
2. `web/backend/schemas.py` 中 `RowState` 新增 `error_type: Optional[str]` 与 `error_code: Optional[str]`，默认 `None`
3. 重新生成 `web/frontend/src/api/types.ts`（运行 `npm run gen:types`）
4. 后端发射端不在本任务实际填充 `error_type`/`error_code`（保持 V1 不破坏现有路径），仅扩协议
5. flag 默认值表写入 `featureFlags.ts` 文件头注释

验收：

1. `featureFlags.ts` 单测覆盖三层覆盖优先级
2. 协议字段在 schemas.py 与 types.ts 一致
3. 后端 pytest 现有用例全绿（不应破坏旧契约）

风险：

1. 协议扩展导致客户端旧代码报错 -> 字段 Optional + 默认 None 保证向后兼容

回退：

1. 移除 featureFlags.ts 与 RowState 新字段，重生成 types.ts

## T1. Today 列表默认态改造

flag：`ff_today_default_view`
目标：实现 C02 默认展示与排序筛选语义。

产出：

1. 行视图默认渲染（沿用现有表格，结构调整）
2. 默认筛选"仅可执行项"（V1 近似见 §3）
3. 排序"价值优先 + 时间压力次级"（V1 近似见 §3）
4. "查看全部"快速切换入口
5. 筛选/排序逻辑写入 `utils/todayView.ts`（纯函数，便于 T10 单测）

验收：

1. 首次进入 Today 即满足默认态
2. 切换"查看全部"不影响数据正确性
3. flag 关闭时回退旧行为

## T2. 执行前轻确认条

flag：`ff_today_light_confirm`
目标：执行前显示非弹窗轻确认信息。

产出：

1. 新组件 `components/today/LightConfirmBar.tsx`
2. 文案："本次将执行 N 条，可随时停止"
3. N 与当前执行集合一致
4. 普通执行不弹窗

验收：

1. 点击执行前可见确认条
2. 与实际执行数量一致
3. flag 关闭时直接执行无确认条

## T3. 执行中交互稳定化

flag：`ff_today_follow_running`
目标：执行中不打断主流程。

产出：

1. 自动滚动到首个 `status==='running'` 的行
2. 执行中允许调整筛选（仅影响显示）
3. 明示提示"仅影响显示，不影响执行"
4. 跟随逻辑写入 `utils/todayView.ts`

验收：

1. 执行中滚动行为稳定
2. 改筛选不改变执行任务集合
3. flag 关闭时不滚动

## T4. 完成后摘要停留

flag：`ff_today_summary_stay`
目标：任务完成后停留在结果摘要区。

产出：

1. 新组件 `components/today/SummaryPanel.tsx`
2. done/error/canceled 统一进入摘要区
3. 摘要包含成功/失败/待处理计数
4. 提供"进入失败分组"快捷入口（联动 T5）

验收：

1. 终态后不跳到列表顶部
2. 可直接进入失败分组处理
3. flag 关闭时无摘要面板

## T5. 失败分组构建

flag：`ff_today_failure_groups`
目标：实现 C03 分组语义。

产出：

1. 新组件 `components/today/FailureGroupsPanel.tsx`
2. 新工具 `utils/failureGrouping.ts`：按 `error_type` -> `error_code` -> `phase` 三级 key 兜底（T0 协议字段缺失时只用 phase）
3. 按失败数量降序
4. 默认展开失败最多分组

验收：

1. 分组稳定且可复现（同输入同输出）
2. 排序与默认展开符合规则
3. flag 关闭时不渲染失败分组面板

## T6a. 后端组级重试入口

目标：扩展后端入口接受 voc_id 子集。

产出：

1. 修改 `web/backend/routers/study.py` 的 `POST /api/study/process`：接受可选 body `{voc_ids?: string[]}`
2. `voc_ids` 为空 -> 沿用旧路径（`momo.get_today_items`）
3. `voc_ids` 非空 -> 仅按子集执行 workflow.process_word_list
4. schemas.py 新增 `ProcessRequest` 模型
5. 同步重生成 `types.ts`
6. 新增 `tests/web/test_v1_acceptance.py` 覆盖：
   - 不传 body 时旧行为不变
   - 传 voc_ids 时仅执行子集
   - profile lock 行为不变

验收：

1. 旧调用 `apiPost('/api/study/process')` 无 payload 行为不变
2. 新调用 `apiPost('/api/study/process', {voc_ids: [...]} )` 仅执行子集
3. 新测试全绿，旧测试无回归

## T6b. 前端组级重试动作

flag：`ff_today_group_retry`
目标：实现组级全量重试链路。

产出：

1. `FailureGroupsPanel.tsx` 中"重试该组 N 条"按钮
2. 复用 T2 轻确认条："将重试 N 条"
3. 调 T6a 入口 `apiPost('/api/study/process', {voc_ids})`
4. 重试后刷新分组状态

验收：

1. 重试范围正确（仅该组）
2. 结果状态可见
3. flag 关闭时不显示按钮

## T7. 大批量二次确认门禁

flag：`ff_today_bulk_guard`（默认 ON，独立于其他 flag）
目标：避免误触发大规模重试。

产出：

1. 失败组条目 >100 时强制二次弹窗
2. 弹窗含影响范围与回退提示
3. 阈值常量 `BULK_RETRY_THRESHOLD = 100` 集中在 `featureFlags.ts`

验收：

1. <=100 不触发二次弹窗
2. >100 必触发
3. 即使 `ff_today_group_retry` 开启，`ff_today_bulk_guard` 关闭后也跳过弹窗（只在显式关闭时）

## T8. 残留失败高亮

flag：`ff_today_residual_highlight`
目标：重试后仍失败项可直接定位。

产出：

1. 重试后保持当前分组上下文（不收起面板、不切换分组）
2. 仍失败项视觉高亮（红色描边或背景）

验收：

1. 不跳离当前分组
2. 失败残留可一眼识别
3. flag 关闭时无特殊高亮

## T9. Feature Flag 总开关与回退

目标：保证 V1 可快速回退。

产出：

1. 所有 V1 flag 在 `featureFlags.ts` 集中维护，含默认值表
2. 一键全关：URL `?ff_off=v1` 或 localStorage 设置 `ff_off=v1`
3. 文档化开关说明（在 `featureFlags.ts` 文件头）

验收：

1. 关闭 flag 后 Today 回到 v1 修订前的稳定行为
2. 无残留异常状态
3. 一键全关生效

## T10. 验证与发布准备

目标：合入前完成门禁与说明。

门禁口径（已确认）：

1. **(a) 后端 pytest**：`python -m pytest tests/web/ -v -m "not slow"` 全绿
   - 必含 `test_study.py`、`test_tasks_api.py`、`test_v1_acceptance.py`（T6a 新增）
2. **(b) 前端单测**：引入 Vitest，覆盖 `utils/todayView.ts`、`utils/failureGrouping.ts`、`utils/featureFlags.ts` 三个纯函数文件
   - 命令：`npm --prefix web/frontend run test`
3. **build + typecheck**：`npm --prefix web/frontend run build`（已含 `tsc -b`）

产出：

1. 三项门禁运行结果（命令 + 摘要）
2. 风险与回退说明
3. flag 默认值清单
4. CHANGELOG 同步

验收：

1. 三项门禁全通过
2. 验收记录完整

---

## 5. 建议执行顺序

1. **串行前置**：T0
2. **并行**：A 组（T1->T2->T3->T4） 与 B 组（T5->T8 + T6a）
3. **依赖收尾**：T6b（依赖 T6a + T2）-> T7（依赖 T5）-> T9 -> T10

依赖关系：

- T1-T8 全部依赖 T0
- T6b 依赖 T6a 与 T2
- T7 依赖 T5
- T8 依赖 T6b
- T9 依赖 T1-T8
- T10 依赖 T9

---

## 6. 交付清单模板（每个任务）

1. 任务编号
2. 改动文件列表
3. 变更说明（3-6 条）
4. 风险与回退方式
5. 验证命令与结果

---

## 7. 给执行者的硬约束

1. 不得破坏 Today 日常可用性（GLOBAL_TODAY_GUARDRAILS）
2. 不得跳过全局门禁
3. 无验证证据不得声称完成
4. 发现跨模块风险要先停并上报
5. 任何超出 T0-T10 的范围扩展都要先暂停并上报
