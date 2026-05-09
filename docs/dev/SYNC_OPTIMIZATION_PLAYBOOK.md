# SYNC_OPTIMIZATION_PLAYBOOK.md

## 目的

提供同步系统优化的可执行路线，以及与 REFACTOR_PROGRESS Phase 4/5/6 的依赖映射。

适用问题：后台笔记同步影响前端页面加载、页面切换、任务响应速度。

---

## 路径关系（修订）

原文档曾把"路径 A"（最小改造）与"路径 B"（完整改造）描述为可二选一，并宣称"跳过 A、直接 B"。复盘后发现：

- A1（API 查询降重）是任何调度优化的**前置基石**——若 API 接口本身做全表扫描，再优秀的同步调度也救不了页面卡顿。
- A4（运行期 Kill Switch）应与 Phase 6「配置现代化」合并落地，避免做两遍。
- A2/A3（warmup 非阻塞 / 今日让路）的目标会被 Path B 的优先级调度天然吸收。

因此修订后的关系为：

```
A1 查询降重           → 必做前置（独立 Phase 4.5，1 天工作量）
A2/A3                 → 被 Path B 吸收
A4 Kill Switch        → 合并到 Phase 6 配置现代化

B1 优先队列 + 防饿死  → Phase 4 ★
B2 单消费者维持       → Phase 4 ★（已是单消费者，本步只做"per-profile 暂停"）
B3 闲时引擎           → 依赖 Phase 5 监控基础设施
B4 前端协同           → 独立到 web_ui 工作区，依赖 Phase 4.5
B5 可观测性           → Phase 5
```

---

## A. 查询降重（Phase 4.5）

### A1. API 接口查询降重

目标：把"高频路径中的重查询"替换为"轻量统计"。

执行项：

1. `stats/summary` 中的待同步数量改为 `COUNT(*)`，禁止 `get_unsynced_notes()` 全量读取计数。
2. `sync/status` 的队列深度同样改为 `COUNT(*)`。
3. 冲突列表默认 limit 控制在小范围（如 20），保持分页。
4. 任何高频 GET 接口禁止做 `SELECT * FROM notes` 后再 `len(...)`。

验收：

- `GET /api/stats/summary` 与 `GET /api/sync/status` 响应时间稳定 <100ms。
- 真正实现"页面打开/切换不卡"——这是用户感知的根因，调度优化只能缓解、不能根治。

### A4. 运行期 Kill Switch（合并到 Phase 6）

目标：出现性能回退时可快速止损。配置项：

- `AUTO_WARMUP_SYNC_ENABLED`
- `SYNC_STATUS_HEAVY_QUERY_ENABLED`
- `BACKGROUND_RETRY_ENABLED`

落地方式：与 Phase 6 `pydantic-settings` 迁移合并实施，作为一组开关写在配置 schema 中。

---

## B. Path B 完整体系

### B1. 优先队列调度（Phase 4 ★）

目标：同步系统具备优先级与防饿死能力。

执行项：

1. `core/sync_manager.py` 的 `sync_queue` 由 `queue.Queue` 升级为 `queue.PriorityQueue`（**threading 模型，不引入 asyncio**）。
2. 任务条目封装为 `(priority, seq, payload)`：seq 单调递增，保证同优先级 FIFO；同时避免 dict 直接比较引发 TypeError。
3. 优先级语义：
   - **P1**：今日任务产出的同步项（`study_workflow.py` / `study_flow.py`）
   - **P2**：用户主动触发（`web/routers/sync.py` 的 flush/retry）
   - **P3**：warmup 入队补偿（`user_context._warmup_async`）
   - **P4**：预留给未来的延迟重试，本期不强制使用
4. 出队策略：**严格优先级**——P 高的有就先处理。
5. **防饿死保底**：worker 维护 `consecutive_high_count`，连续处理 5 个 P1 后强制让一个 P2/P3 出队。简化于原 PLAYBOOK 的 60/25/15 加权方案，因为单消费者实际吞吐 ~5 条/秒（受 maimemo HTTP 频控限制），权重精度无意义。

### B2. 单消费者维持 + per-profile 暂停（Phase 4 ★）

目标：多 profile 场景下，前台 active profile 永远优先。

**架构现实**：当前每个 profile 一个 `UserContext` → 一个 `StudyWorkflow` → 一个 `SyncManager` → 一个独立 worker thread。这意味着 **N 个 profile = N 个 worker 各拉各的队列**，原 PLAYBOOK 提的"全局单消费者优先队列"在当前架构下不成立。

修订方案：**per-profile 单消费者 + ActiveProfileRegistry 暂停拉取**

1. 新增进程级单例 `core/active_profile_registry.py`：
   - `set_active(profile_name)` / `get_active() -> str | None` / `is_active(profile_name) -> bool`
   - 内部用 `threading.Lock` 保护读写。
2. `web/backend/deps.py::_resolve_profile()` 中调用 `set_active(profile)`——每个 API 请求都自然更新"最近活跃 profile"。
3. SyncManager worker 出队前自检：
   - 若 `ActiveProfileRegistry.get_active()` 不是本 profile，且当前任务优先级 ≥ P3 → 重新入队，`time.sleep(0.5)` 后 continue。
   - P1/P2 始终立即处理（即便 profile 不 active，也是用户已经"主动要求"了）。

**单消费者属性**：保持不变。SyncManager 仍只起一个 worker thread，本期禁止改造为 ThreadPoolExecutor。

**抢占粒度**：单任务级（每处理完一条 maimemo HTTP 同步，下一轮 worker loop 重新查询活跃 profile / 优先级）。原 PLAYBOOK 的"小批次 20-50 条 / <100ms"概念在 maimemo 网络同步上不成立——一条一次 HTTP，几百 ms 起。

### B3. 闲时同步引擎（依赖 Phase 5）

目标：真正实现"闲时加速，高峰让路"。

**前置依赖**：

- 需要 P95 延迟、锁等待、API 请求频率指标——这些由 Phase 5 的 `LogStatistics` 提供。
- 在监控基础设施落地前，本节内容**不实施**。

预留设计要点（Phase 5 阶段实施时参考）：

1. Idle detector 进入条件需连续满足 5-10 秒（防抖）。
2. 退出 idle 立即响应，不延迟。
3. 仅在稳定 idle 状态下处理 P3+ 自动补偿任务。

### B4. 前端协同（独立 web_ui 工作区）

**前置依赖**：A1（Phase 4.5）。否则 hover prefetch 会放大重查询代价。

设计要点（不在 REFACTOR_PROGRESS 范围内，独立 PR）：

1. **Hover 悬停预获取**：导航栏 / 按钮 `onMouseEnter` 触发 React Query 的 `prefetchQuery`，利用 200ms 反应时间差实现"瞬间切页"。
2. 关键页面骨架屏 + 核心字段优先渲染。
3. API 降级元数据（`meta._is_degraded: true`），前端非侵入式提示。
4. 同步状态页"实时统计 / 延迟明细"分层。

### B5. 可观测性与自动策略（Phase 5）

完全等同于 REFACTOR_PROGRESS Phase 5 内容：

1. 指标：API P95、同步吞吐、队列长度、锁等待、重试率。
2. 阈值告警自动触发降级。
3. 每日同步健康摘要。

---

## 与 REFACTOR_PROGRESS 的映射

| 本文档章节 | REFACTOR_PROGRESS 阶段 |
|---|---|
| A1 查询降重 | Phase 4.5 |
| A4 Kill Switch | Phase 6 配置现代化 |
| B1 优先队列 + 防饿死 | Phase 4 ★ |
| B2 per-profile 暂停 | Phase 4 ★ |
| B3 闲时引擎 | Phase 5 |
| B4 前端协同 | 独立 web_ui 工作区，依赖 Phase 4.5 |
| B5 可观测性 | Phase 5 |

---

*本文档自 2026-05-08 修订，对齐代码现状与 REFACTOR_PROGRESS。原版本在 git history 中可查。*
