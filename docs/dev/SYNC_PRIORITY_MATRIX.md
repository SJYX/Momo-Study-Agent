# SYNC_PRIORITY_MATRIX.md

## 目标

将"同步任务"从可能影响前端加载的后台活动，改造成有明确优先级、可降级的调度体系。

核心原则：

1. 前端关键请求优先于任何同步
2. 今日任务优先于未来任务与补偿同步
3. 闲时尽量清空积压，高峰时自动让路

---

## 一、API 接口的硬约束（不是同步任务，不入队列）

> ⚠️ 本节列出的是 **HTTP 接口**，不是同步任务。它们的"优先级"概念是"不可被同步阻塞"的硬约束，与下一节的同步任务 P1~P4 是两个不同维度。

### 永不阻塞 / 必须轻量的接口

- `GET /api/session`
- `GET /api/users`
- `GET /api/stats/summary`（**仅轻量统计版本**，依赖 Phase 4.5 完成 `COUNT(*)` 改造）
- `GET /api/study/today`
- `GET /api/study/future`
- 静态资源与入口：`/`, `/assets/*`, `index.html`

要求：

- 不做全量未同步列表扫描
- 不做重查询拼接
- 不等待同步 worker 完成
- 目标：P95 稳定 <100ms，超时优先返回降级数据
- **支持前端预获取（Pre-fetching）**：接口必须保持极度轻量，以随时响应基于 `Hover` 的高频预加载请求（前端 hover prefetch 详见 PLAYBOOK B4，**前置依赖 Phase 4.5**）。

---

## 二、同步任务的优先级矩阵（执行层）

> 本节描述的是 `core/sync_manager.py::sync_queue` 中**实际入队的同步任务**的优先级。

### 任务元数据

```python
{
  "priority": Priority.P1 | P2 | P3 | P4,
  "source": "today" | "future" | "manual" | "warmup" | "retry",
  "profile_id": "<owning profile name>",
  "voc_id": "...",
  "spell": "...",
  "interpretation": "...",
  "tags": [...],
  "force_sync": bool,
}
```

### 优先级分级

- **P1** 今日任务同步项
  - 来源：`core/study_workflow.py::_run_pipeline_for_word` 等今日任务管线产出
  - 调用点：`study_workflow.py:285`、`core/study_flow.py:66`
  - 出队策略：最高优先级，立即处理

- **P2** 用户主动触发
  - 来源：用户在 UI 上点击"立即同步" / "重试冲突"
  - 调用点：`web/backend/routers/sync.py:145`
  - 出队策略：仅次于 P1

- **P3** warmup 自动补偿
  - 来源：profile 首次进入时扫描未同步笔记的批量入队
  - 调用点：`web/backend/user_context.py:244`（`_warmup_async`）
  - 出队策略：可被 active profile 切换暂停

- **P4** 预留
  - 预留给未来的延迟重试 / 定时补偿

### 出队策略

**严格优先级 + 防饿死保底**：

1. PriorityQueue 默认按 `priority` 字段排序，同优先级按 `seq` FIFO。
2. Worker 维护 `consecutive_p1_count`：
   - 每处理一个 P1 任务，计数 +1
   - 达到 5 时，强制下一轮先尝试出队 P2/P3（若有），处理后计数清零
   - 处理任何非 P1 任务时计数清零
3. 防饿死的实现简化于原矩阵的"60%/25%/15%"权重——单消费者吞吐受 maimemo HTTP 频控制约（~5 条/秒），权重精度无意义。

### 抢占粒度

**单任务级**（不是批次级）：

- maimemo 同步是一条一次 HTTP，每条几百 ms。"小批次抢占"概念套不上。
- worker 每处理完一条任务，下一轮 loop 自然重新查询当前 active profile / 优先级。
- 禁止中断进行中的 HTTP 调用——网络回滚代价不值得。

---

## 三、多 Profile 协同调度

### 架构现状

每个 profile 有独立 `UserContext` → `StudyWorkflow` → `SyncManager` → 独立 worker thread。

**N 个 profile = N 个 worker 各跑各的队列**。这意味着没有"全局单消费者优先队列"——原矩阵此处描述与代码现实不符，已修订。

### per-profile 暂停拉取（Phase 4 实现）

通过进程级 `core/active_profile_registry.py` 单例协同：

- 前端通过 `X-Momo-Profile` header 标识当前活跃 profile
- 每个 API 请求经 `web/backend/deps.py::_resolve_profile()` 自动调用 `ActiveProfileRegistry.set_active(profile)`
- 各 profile 的 SyncManager worker 出队前自检：

| 当前任务优先级 | 本 profile 是 active？ | 行为 |
|---|---|---|
| P1 | 任意 | 立即处理（用户已经在跑今日任务） |
| P2 | 任意 | 立即处理（用户主动点击） |
| P3 | 是 | 立即处理 |
| P3 | 否 | 重新入队，sleep 0.5s 后 continue |
| P4 | 是 | 立即处理 |
| P4 | 否 | 重新入队，sleep 0.5s 后 continue |

效果：用户当前前台 profile 的 P1/P2 同步立即跑，**后台挂起的其他 profile 的自动补偿（P3/P4）会被压制**——用户感知是"切换到我的 profile，立刻顺畅"。

---

## 四、数据库与查询约束

由 **Phase 4.5（PLAYBOOK A1）** 落实，本矩阵仅复述要求：

必须避免：

1. 高频接口中 `get_unsynced_notes()` 全字段全量读取后 `len(...)`
2. 前端加载阶段触发冲突明细重查询
3. warmup 一次性全量扫描并立刻全入队（保留分批，warmup 本身在 P3 优先级下被自然限速）

建议替代：

1. `COUNT(*)` 统计待同步数量
2. 冲突列表分页 + 默认小页（≤20）
3. warmup 仅做"最小字段 + 分批入队"

---

## 五、闲时调度与降级（依赖 Phase 5）

> ⚠️ 本节内容依赖 Phase 5 的 `LogStatistics` 监控基础设施。在 Phase 5 落地前，**不实施本节内容**。

### 闲时判定（Phase 5 后实施）

需满足所有条件 + 防抖：

1. 最近 N 秒无 P0 接口请求高峰
2. 过去 10 秒内未收到 P1 级别任务且 P1 队列为空
3. DB 锁等待低于阈值
4. API P95 未超阈值

状态切换防抖（Debounce）：

- **进入闲时**：连续满足闲时条件 ≥5 秒才启动 P3/P4 加速
- **退出闲时**：任一条件不满足立即响应

### SLO 与协同降级（Phase 5 后实施）

监控阈值：

- `GET /api/stats/summary` P95 >300ms
- `GET /api/study/today` P95 >400ms
- DB 锁等待 P95 >100ms

触发后自动动作：

1. 暂停 P3/P4 自动补偿
2. 关键接口下发降级元数据（`meta._is_degraded: true`）
3. 前端非侵入式提示（"系统繁忙，数据正在排队同步…"）

---

## 六、验收标准

| 阶段 | 验收点 |
|---|---|
| Phase 4 调度地基 | 多 profile 同时在跑时，active profile 的 P1/P2 同步不被其他 profile 的 P3 warmup 拖累 |
| Phase 4 调度地基 | P1 连续 5 个后让 1 个 P2/P3，P2/P3 不饿死 |
| Phase 4.5 查询降重 | `/api/stats/summary` 与 `/api/sync/status` P95 <100ms |
| Phase 4.5 查询降重 | 页面首次进入与切换不因同步出现明显卡顿 |
| Phase 5 闲时引擎 | 闲时队列可持续下降，非闲时能自动让路 |

---

*本文档自 2026-05-08 修订，对齐代码现状（per-profile SyncManager）与 REFACTOR_PROGRESS Phase 4/4.5 范围。*
