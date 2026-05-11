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
   - **P4**：预留给未来的延迟重试
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

**单消费者架构**：每个 profile 一个 SyncManager worker thread（多 profile = 多 worker 互不干扰）。

**抢占粒度**：单任务级（每处理完一条 maimemo HTTP 同步，下一轮 worker loop 重新查询活跃 profile / 优先级）。这与 HTTP 请求的几百 ms 粒度相匹配。

### B3. 闲时同步引擎（依赖 Phase 5）

**状态**：✅ 已完成（2026-05-11，与 B5 指标系统同步落地）。

**前置依赖**：

- ~~Phase 5 LogStatistics~~ → 实际由 PLAYBOOK B5 新建的 `core/metrics.py` 替代（Phase 5 决议不激活 LogStatistics）

落地内容：

1. `core/sync_manager.py::_is_idle(profile)` 消费 `MetricsCollector` 的滚动百分位：
   - `api.duration_ms` P95 < 200ms
   - `sync.queue.depth` P95 < 5
   - `db.batch_write.duration_ms` P95 < 100ms
2. 进入条件需连续满足 ≥5 秒（`IDLE_DEBOUNCE_S`）防抖，退出时立即响应（任一指标超阈值即重置 `_idle_since`）。
3. 仅在稳定 idle 状态下处理非 active profile 的 P3/P4 自动补偿任务；非 idle 时回退到 Phase 4 的 active profile 暂停。
4. Kill Switch：`IDLE_ENGINE_ENABLED=False` 让 `_is_idle` 永远返回 False，行为退化到 Phase 4。

### B4. 前端协同（独立 web_ui 工作区）

**状态**：✅ 已完成（2026-05-11）。

**前置依赖**：A1（Phase 4.5）。否则 hover prefetch 会放大重查询代价。

落地内容（独立 PR / web_ui 工作区）：

1. **Hover 悬停预获取**：Sidebar `NavLink` `onMouseEnter` 触发 React Query `prefetchQuery`，按路由映射在 `web/frontend/src/queries/prefetch.ts` 集中维护；WordLibrary 行 hover 预拉详情。
2. **关键页面骨架屏**：`web/frontend/src/components/ui/Skeleton.tsx` 提供 `SkeletonLine` / `SkeletonCard` / `SkeletonRow` 三变体，应用于 Dashboard / TodayTasks / WordLibrary。
3. **API 降级元数据**：后端 `StatsSummary` / `OpsStatsResponse` / `SyncStatusResponse` 统一加 `degraded` / `degraded_reason` 字段（本期只开通道，后端不主动写入）；前端 `DegradedBanner.tsx` 原子组件挂在 Dashboard / SyncStatus，渲染黄色非侵入式提示。
4. **Dashboard 迁 React Query**：最后一个 useState/useEffect holdout，迁完才能受益于 prefetch 与 invalidation 统一管理。
5. **不做（推迟到 B5 之后）**：MATRIX 提到的"同步状态页延迟明细分层"——延迟数据源依赖 B5 指标系统。

### B5. 可观测性与自动策略（Phase 5）

**状态**：✅ B5 指标系统已完成（2026-05-11）；自动策略（SLO 告警 → Kill Switch）推迟。

落地内容：

1. **指标层 `core/metrics.py`**：进程内 `RollingWindow`（300s TTL + 1000 max_size）+ `MetricsCollector`（按 profile/metric 隔离），提供 P50/P95/P99 + count。
2. **采集点**：
   - API timing middleware（`web/backend/app.py`）记 `api.duration_ms`
   - `database/execution_engine.py` 两处记 `db.batch_write.duration_ms` / `db.idle_sync.duration_ms`
   - `core/sync_manager.py` worker 每轮采样 `sync.queue.depth`，每条同步记 `sync.task.duration_ms`
3. **Endpoint**：`GET /api/ops/metrics?profile=...` 与 `POST /api/ops/metrics/reset?profile=...`
4. **消费者**：B3 闲时引擎实时读取，OpsMonitor 前端面板可后续接入

**未做（推迟）**：

- 自动 SLO 告警 → Kill Switch 联动（手动 flag 即可应急）
- 每日健康摘要 / 离线 dump
- LogStatistics 旧组件清理

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
