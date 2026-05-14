# 「今日任务」全链路审查报告 (2026-05-14)

> **审查范围**:从 `get_today_items` → 三表判重 → 状态分类 → AI 生成 → 落库 → 入队 → momo 同步 → 状态写回的完整链路
> **审查焦点**:逻辑正确性、状态机自洽性、数据一致性
> **审查方式**:静态代码审查,未实际复现行为
> **审查分支**:`feat/web-ui`(HEAD: `b97c0ba`)

---

## 0. 整体结论先行

链路骨架是**清晰且收敛**的:写队列、Embedded Replica、5 态 + sync_status 数值的双层映射、批量刷盘、防饿死调度——这些机制单独看都是经过深思熟虑的。

但跨模块对齐有 **3 处真问题** + **若干文档/死代码债**。最严重的是:

> **`sync_status=5`(failed) 的词在再次点击「处理今日任务」时,会被静默渲染成"已完成"** —— 用户永远看不到它失败了。这是肉眼可见的状态机泄漏。

下面按链路顺序展开。

> 📌 **同日续审更新**:[§7 同步冲突专项审查](#7-同步冲突专项审查-续审) 厘清了 `sync_status=2` 的完整链路。**关键背景**:冲突机制是为了保护用户早期在墨墨手动创建的释义不被 AI 覆盖 —— 这是 feature,不是 bug。续审保留 1 处严重 bug(**H3** 死代码三件套)和 1 处 UX 文案问题(**H4** 重试按钮命名误导),外加 1 个值得长期投入的设计方向(`last_synced_content` 字段区分手写 vs AI 上次版本)。

> 📌 **续审 2(查重逻辑)**:[§8 查重逻辑专项审查](#8-查重逻辑专项审查-续审-2) 发现 `partition_by_processability` 与 `enrich_with_states` 之间存在重复劳动,且分组真值表在边界场景**会静默丢词**(M5,DRY_RUN 处理过的词在正式模式下会消失)。推荐重写为基于 `WordState` 一次 LEFT JOIN 直接分组,可同时修复丢词 + N+1 + 双重 backfill 三个问题。

---

## 📊 修复进度跟踪(实时更新)

| 编号 | 问题 | 状态 | Commit |
|---|---|---|---|
| **H1** | failed 词在跳过分支被静默显示为"完成" | ✅ 已修复 | [`07b0c55`](#-h1--failed-状态被静默显示为完成--已修复-07b0c55) |
| **H2** | `word_progress_history` 兜底死代码 / SSoT 模糊 | ✅ 已修复(随 M5 一并) | [`8282bd0`](#-h2--word_progress_history-兜底是半死代码ssot-实际模糊--已修复-8282bd0随-m5-重写一并解决) |
| **H3** | `conflict_sync_queue` / `on_conflict` 三件死代码 | ✅ 已修复 | [`d6b0d24`](#-h3--_defer_maimemo_conflict--conflict_sync_queue--on_conflict-全是死代码--已修复-d6b0d24) |
| **H4** | "重试冲突"按钮文案与行为不符(UX) | ✅ 已修复 | [`87c7da6`](#-h4--重试冲突按钮的文案与行为不符ux-问题非逻辑-bug--短期已修复-87c7da6) |
| **M5** | partition 与 enrich 重复劳动 + DRY_RUN 词静默丢失 | ✅ 已修复(含 M6/M7/L6/L8) | [`8282bd0`](#-m5--partition_by_processability-与-enrich_with_states-重复劳动且边界场景静默丢词--已修复-8282bd0) |
| M1 | sync_status 数值 3/4 是死状态但代码假装存在 | ✅ 已完成 | |
| M2 | `on_mark_processed` 是空回调 | ✅ 已完成 | |
| M3 | SyncManager.shutdown 注释/超时不一致 | ✅ 已完成 | |
| M4 | 释义匹配算法可能误报冲突 | ✅ 已完成 | |
| L1-L7 | 杂项性能/文档/UX | ✅ 已完成 | |
| **设计** | 6.1 / 6.2 / 6.3 / 7.6.x / 8.6.x | ✅ 已全链路实装 | |

> 修复链接锚点用 GitHub markdown anchor 风格(小写、空格变 -)。

---

---

## 1. 链路与状态机回顾

### 1.1 数据通路

```
[云端 get_today_items] → normalize_cloud_items → enrich_with_states
                          ↓
              partition_by_processability (三表判重)
                          ↓
        ┌────────── processed ──────────┐    └─── pending ───┐
        │  显示状态(skipped 分支)       │       │ AI 批处理 │
        └────────────────────────────────┘       └─ save_ai_word_notes_batch (sync_status=0)
                                                   └─ queue_maimemo_sync(force_sync=True)
                                                       ↓
                                          [worker] momo.sync_interpretation
                                                       ↓
                                  1=synced  2=conflict   其他=failed(5)
                                  ↓批量刷盘  ↓单条立即写  ↓单条立即写
                              processed_words + sync_status=1
```

### 1.2 状态映射(代码事实)

| sync_status 写入点 | 实际可达值 | derive_state 分支 | state_to_where_clause 分支 |
|---|---|---|---|
| save_ai_word_notes_batch 默认值 | **0** | LOCAL_READY | LOCAL_READY 范围 |
| momo 同步成功 → flush_pending_writes | **1** | SYNCED | = 1 |
| momo 同步冲突 → set_note_sync_status | **2** | CONFLICT | = 2 |
| invalid_res_id / sync_incomplete → set_note_sync_status | **5** | FAILED | = 5 |
| ~~queued~~ | 3(代码里**永不写入**) | LOCAL_READY | LOCAL_READY 范围 |
| ~~syncing~~ | 4(代码里**永不写入**) | LOCAL_READY | LOCAL_READY 范围 |

代码注释明确说明 3/4 是"虚化为内存态广播,不再硬写数据库"([../../core/sync_manager.py:139-140](../../core/sync_manager.py#L139-L140)、[../../core/sync_manager.py:318](../../core/sync_manager.py#L318))。但 `derive_state`、`state_to_where_clause`、`current_status not in (0, 3)` 等多处仍按 6 值实现 —— 形成幽灵分支。

---

## 2. 问题清单(按严重程度)

### ✅ H1 — failed 状态被静默显示为"完成" *(已修复 `07b0c55`)*

**位置**:[../../core/study_workflow.py:210-227](../../core/study_workflow.py#L210-L227)

```python
for item in processed_items:
    phase = "skipped"
    status = "done"
    reason = ""
    try:
        note = get_local_word_note(item.voc_id)
        sync_status = int((note or {}).get("sync_status", 0) or 0)
        if sync_status == 0:
            phase = "sync_pending"; status = "pending"; reason = "本地已生成,待上传同步"
        elif sync_status == 2:
            phase = "sync_conflict"; status = "warning"; reason = "云端释义冲突,待处理"
    except Exception:
        pass
```

**问题**:只识别 0 和 2,未识别 5(failed)。流程如下:

1. 某词第一次处理时 momo 返回 `invalid_res_id`,被 [../../core/sync_manager.py:434-441](../../core/sync_manager.py#L434-L441) 写入 `sync_status=5`
2. 该词的 `ai_word_notes` 已存在,下次进入今日任务流程,`_get_ids_with_local_notes` 把它分到 `processed_items`
3. 走到这段 skipped 分支 → `sync_status=5` 不命中 0/2 → 使用默认 `phase="skipped" status="done"`

**用户表现**:**failed 的词每次都显示"已完成"**,用户永远不知道有失败,只有去查数据库才能发现。

**对比**:[../../web/backend/routers/study.py:217-223](../../web/backend/routers/study.py#L217-L223) 的状态查询 API 是正确映射的(有 `WordState.FAILED → "sync_failed"`),但这条 row_status 事件流不是。两者不一致。

**建议**:

```python
elif sync_status == 5:
    phase = "sync_failed"
    status = "error"
    reason = (note or {}).get("match_reason") or "上传失败"
```

并考虑把 5 的词从 `processed_items` 重新分入"待处理"或单独的"待用户决策"组,否则它**没有任何路径会被重新尝试**(除非用户手动改 DB)。

---

### ✅ H2 — `word_progress_history` 兜底是"半死代码",SSoT 实际模糊 *(已修复 `8282bd0`,随 M5 重写一并解决)*

**位置**:[../../core/word_service.py:104-150](../../core/word_service.py#L104-L150)、[../../database/progress_repo.py:122](../../database/progress_repo.py#L122)

`partition_by_processability` 用 3 套兜底判定"已处理":

1. `filter_unprocessed` — 查 `processed_words` ∪ `ai_word_notes`
2. `_get_tracked_ids` — 查 `word_progress_history`
3. `_get_ids_with_local_notes` — 再查 `ai_word_notes`(带内容非空过滤 + 自愈 backfill)

**事实**:`log_progress_snapshots`(唯一向 `word_progress_history` 写入的函数)在生产代码里**没有任何调用点**(grep 验证,只在 `tests/` 出现)。

那么 `word_progress_history` 的数据从哪来?**只能是 Turso Embedded Replica 从云端 sync 下来**。也就是说:

- **单机用户**:这表永远为空,`_get_tracked_ids` 永远返回空集 → 第 2 步等于无效兜底
- **多端协同用户**:这表可能从其他端同步过来(但另一端也没写入,所以也没数据)
- **历史用户**(早期版本写过该表):仍可能命中

更严重的问题是**语义可疑**:即使该表有数据,词出现在历史快照里 ≠ 词被本机 AI 处理过。把它当作"已处理"跳过 AI 会**漏处理一个本该处理的新词**。

第 3 步 `_get_ids_with_local_notes` 已经完整覆盖了"有笔记 = 已 AI 处理"的语义,且配带自愈 backfill —— 这才是真兜底。第 2 步要么删,要么需要明确这是什么语义。

**建议**:

- 删除 `_get_tracked_ids` 调用,或显式标注"仅历史兼容,不再写入"
- 把 SSoT 明确为:`ai_word_notes.voc_id 存在(且至少一项内容字段非空) ⇔ 已 AI 处理`
- [../../docs/dev/REFACTOR_PROGRESS.md:241](../../docs/dev/REFACTOR_PROGRESS.md#L241) 已经标识到了这个问题("3 套兜底语义不一"),但没收尾

---

### 🟡 M1 — sync_status 数值 3 / 4 是死状态,但代码处处假装它们存在

**涉及位置**:

- 语义定义:[../../database/word_state.py:32-44](../../database/word_state.py#L32-L44) — 文档说有 0-5 共 6 个值
- 推导规则:[../../database/word_state.py:52](../../database/word_state.py#L52) — `processed or sync_status in (0, 3, 4)` 走 LOCAL_READY
- where 子句:[../../database/word_state.py:75-79](../../database/word_state.py#L75-L79) — `n.sync_status IN (0, 3, 4)`
- 自愈触发:[../../database/word_repo.py:553](../../database/word_repo.py#L553) — `sync_status in (0, 3, 4)` 触发 backfill
- worker 检查:[../../core/sync_manager.py:313](../../core/sync_manager.py#L313) — `if current_status not in (0, 3): skip`
- API 文档:[../../database/notes_repo.py:77-83](../../database/notes_repo.py#L77-L83) — 列出 6 个状态值

**事实**:没有任何写入点会写 3 或 4。注释明确说"虚化为内存态广播"([../../core/sync_manager.py:139-140](../../core/sync_manager.py#L139-L140)、[../../core/sync_manager.py:318](../../core/sync_manager.py#L318))。

**风险**:

- 文档误导,后人按 6 值实现新代码,引入幽灵分支
- worker 的 `current_status not in (0, 3)` 实际等价于 `current_status != 0` —— 复杂度膨胀
- where 子句的 `(0, 3, 4)` 多查了两个永不命中的常量

**建议**:二选一

- **(A)** 保留虚化注释,把代码里所有 `(0, 3, 4)` 折叠到 `= 0`,把文档里 3/4 标"已废弃"
- **(B)** 让 queue/worker 真的写 3 和 4(回归原设计),则要解决写锁争用 —— 这是当初虚化的原因

(A) 更小代价。

---

### 🟡 M2 — `on_mark_processed` 是空回调,但 sync_manager 把它当真接口

**位置**:

- 空实现:[../../core/study_workflow.py:34-36](../../core/study_workflow.py#L34-L36) — `pass`
- 调用点 1(同步成功):[../../core/sync_manager.py:370](../../core/sync_manager.py#L370) — 注释说"内存缓存立即更新(保证后续批次可跳过)"
- 调用点 2(冲突态):[../../core/sync_manager.py:402](../../core/sync_manager.py#L402)

**事实**:回调什么也不做。注释承诺的"内存缓存立即更新"是空话,后续批次能否跳过完全依赖 `_pending_synced` 批量刷盘(2 秒 / 20 条)。

**影响**:

- 当 AI 并发产出 1500 词、worker 每秒同步 ~2 词时,前 18 秒内 90% 的词没被刷盘 → 若期间 `partition_by_processability` 再跑一次(例如其他 profile 的 today),会重复识别为"未处理"。今日任务流程本身是串行的,所以不易触发,但**接口承诺与实现不符**。
- 历史重构([../../docs/dev/REFACTOR_PROGRESS.md:301](../../docs/dev/REFACTOR_PROGRESS.md#L301))曾删除 9 个判重/自愈成员,这个回调是残留。

**建议**:

- 要么实装一个**进程内集合**作为"刚刚 synced 但还没刷盘"的缓存
- 要么删掉回调机制,把构造函数参数去掉,降低接口噪声

---

### 🟡 M3 — `SyncManager.shutdown` 注释/超时不一致,残余任务静默丢失

**位置**:[../../core/sync_manager.py:564-574](../../core/sync_manager.py#L564-L574)

```python
self.sync_worker_thread.join(timeout=5.0)
...
if self.sync_worker_thread.is_alive():
    self.logger.warning("后台同步线程未在 10 秒内结束")   # ⚠️ 说 10,实际 5
```

**问题 1**:注释/日志说 10 秒,代码是 5.0 秒。

**问题 2**(更严重):`estimate_exit_sync_timeout_s`([../../core/sync_manager.py:97-112](../../core/sync_manager.py#L97-L112))会基于历史 P80 计算一个动态超时上限 45 秒,但**没有任何调用方使用它来调整 join 的 timeout** —— 这个估算函数是孤儿。

**问题 3**:5 秒后 worker 若还活着,主线程返回,daemon 线程被进程退出时 kill;残余队列里的"已生成 AI、未上传"的词永久卡在 `sync_status=0`。下次启动时 [../../core/study_flow.py:63](../../core/study_flow.py#L63) / [../../web/backend/user_context.py:246](../../web/backend/user_context.py#L246) 的自愈会重新入队 —— **CLI 端**自愈 OK,**Web 端**用 P3 优先级 + active_profile 暂停 + 闲时引擎,可能延迟很久。

**建议**:

- 修正日志/超时文案统一为 5 秒
- 把 `estimate_exit_sync_timeout_s` 真的接入 `shutdown` 的 join timeout(或删除)
- Web 端自愈优先级改为 P1 或 P2,匹配 CLI

---

### 🟢 L1 — AI 失败的词无任何持久化,无法溯源

**位置**:[../../core/study_workflow.py:74-92](../../core/study_workflow.py#L74-L92)、[../../core/study_workflow.py:269-277](../../core/study_workflow.py#L269-L277)

AI 返回缺失某词 / 整批空结果时,只发 row_status 日志,**不写任何表**。下次今日任务再次识别为 NOT_STARTED,会重新调 AI。

**正向**:自动重试,不需要人工干预。
**负向**:无法看"哪些词 AI 反复失败",也无法在前端把它们与"待处理"区分。如果 AI 一直对某词失败(prompt 缺陷、特殊字符等),会无限循环消耗 token。

**建议**:可选,加一个失败计数表或在 ai_batches 表里关联 failed voc_ids;或者干脆接受这个行为(简单优于复杂)。要不要做取决于实际是否观察到 AI 反复失败的词。

---

### 🟢 L2 — KeyboardInterrupt 取消 AI 不灵敏

**位置**:[../../core/study_workflow.py:246-313](../../core/study_workflow.py#L246-L313)

```python
try:
    with ThreadPoolExecutor(max_workers=ai_workers) as executor:
        ...
except KeyboardInterrupt:
    executor.shutdown(wait=False, cancel_futures=True)
```

Python `with ThreadPoolExecutor` 的 `__exit__` 调用的是 `shutdown(wait=True)` —— Ctrl+C 时主线程**先在 `with` 里阻塞等所有 in-flight AI 任务**(可能是几十秒),然后才进 except。except 里的二次 shutdown 是冗余的。

**建议**(可选):手动管理 executor 而不是用 `with`,在 except 里立刻调 `cancel_futures=True`,然后再 `shutdown(wait=False)`。是体验改进,不影响正确性。

---

### 🟢 L3 — 杂项文档/注释债

- `derive_state` 文档列 6 个 sync_status 值,实际生产 4 个(同 M1)
- `_mark_processed_for_sync` 注释说"sync_manager 回调:当前由 WordService 负责状态管理",但实际什么也不做(同 M2)
- `sync_manager._consecutive_p1_count` 的 reset 时机注释可以再清晰一些

---

## 3. 状态机自洽性结论

代码两层状态机本身是自洽的:`derive_state` ↔ `state_to_where_clause` 双向对齐,5 态枚举到 sync_status 数值的映射严密。

**但**:实际写入的子集只用了 6 个值中的 4 个。设计的"虚化中间态" 在文档/枚举层没体现,带来 M1 的杂讯。

**真正的状态机泄漏只有 H1 一处**:`process_word_list` 的 skipped 分支没把 5 显示出来,这是 UI 层逻辑漏分支,跟数据层无关。

---

## 4. 数据一致性结论

四张相关表的 SSoT 关系建议明确为:

| 表 | 谁写 | 真值含义 |
|---|---|---|
| `ai_word_notes` | `_process_results` 落库 / worker 改 sync_status | "该词被 AI 处理过 + 当前同步状态" |
| `processed_words` | worker 同步成功后刷盘 / backfill 自愈 / dry_run mark_completed | 冗余索引,加速判重 |
| `word_progress_history` | **(目前无人写)** | 仅 Embedded Replica 远端拉取(若曾被写过) |
| `ai_batches` | `save_ai_batch` | AI 批次元数据,与判重无关 |

`ai_word_notes` 应作为 SSoT,`processed_words` 作为快速通道(已经有 backfill 自愈)。第三套兜底(`word_progress_history`)应删除或重新定位语义(见 H2)。

---

## 5. 推荐修复顺序

| 优先级 | 修复 | 工作量 | 风险 | 状态 |
|---|---|---|---|---|
| 🔴 必修 | **H1**:`process_word_list` 加 `sync_status==5` 显示分支 + 考虑是否重新入队 | 小(<10 行) | 低 | ✅ `07b0c55` |
| 🔴 必修 | **H2**:删 `_get_tracked_ids` 或加显式废弃注释 | 小 | 中(需确认无其它语义依赖) | ✅ 已在 M5 重写中一并解决 |
| 🟡 建议 | **M1**:统一 sync_status 实际可达值,删除 3/4 引用 | 中(多处) | 中(若计划恢复 queued/syncing 写入则不要做) | 🚧 待处理 |
| 🟡 建议 | **M2**:删 `on_mark_processed` 死接口,或真的实装内存缓存 | 小 | 低 | 🚧 待处理 |
| 🟡 建议 | **M3**:shutdown 5/10 文案对齐 + Web 端自愈优先级提到 P1/P2 | 小 | 低 | 🚧 待处理 |
| 🟢 可选 | **L1/L2/L3** | 各小 | 低 | 🚧 待处理 |

---

## 6. 留给用户拍板的设计问题

有几处不算 bug,但反映出设计取舍模糊,需要决策:

### 6.1 `sync_status=5` 的词是否应该自动重试?

- **当前**:被永久搁置,只有人工改 DB 才能复活
- **备选**:Web 端给"重试 failed"按钮 / 定期扫表自愈 / 直接降级为 `sync_status=0`
- **建议**:对 `invalid_res_id` 保持 failed(永久不可重试,因为 voc_id 本身错),对 `sync_incomplete` 这种瞬态失败应自动重试 N 次

### 6.2 `word_progress_history` 这张表整体留不留?

- **当前**:无写入,仅 schema 存在;有 `query_weak_words` 在读它做评分
- **选 A**:删表 + 评分降级
- **选 B**:补齐 `log_progress_snapshots` 调用点(在每次 `get_today_items` 后写入)
- **建议**:B,因为薄弱词评分确实依赖这表的历史数据

### 6.3 Web 端的 AUTO_WARMUP 是否要和 CLI 端用同样优先级 P1?

- **当前** P3 + active_profile 暂停 → 多用户场景下卡同步
- **选 A**:Web 端也用 P1(可能影响其他 profile 的 P1 任务)
- **选 B**:首登录给 P1,平时给 P3(细化逻辑)

---

## 7. 同步冲突专项审查 (续审)

> **触发**:原审查 §2 H1 触及 `sync_status=2`,但未深入冲突链路。本节专项审查冲突的判定、生命周期、用户解决路径。
> **续审日期**:2026-05-14(同日)
> **聚焦**:`sync_status=2` 从产生到解决的完整链路

### 7.0 设计意图说明(阅读前必读)

> ⚠️ 本系统的冲突机制是**有意为之的保护机制**,目的是**避免 AI 释义无脑覆盖用户在墨墨 App 手动创建的释义**。

因此,以下行为是 **feature 不是 bug**:

- "冲突无法自动解决"
- "重试按钮不能强推本地版本覆盖云端"
- "墨墨 API 不允许一个 voc_id 第二条释义" — 与本系统的保护意图正好对齐
- 用户解决冲突的**正确路径**:去墨墨 App 手动删除冲突释义 → 本系统下次同步会自动 create 上传

在该语义下,续审真正成立的问题只有:

1. **死代码污染**(§7.3 H3):保护机制不需要的多余间接层,可直接删除
2. **文案误导**(§7.3 H4 — 已降级为 UX):按钮叫"重试冲突"暗示了"解决",但实际只能"复查云端是否还冲突"
3. **判定算法误报**(§7.3 M4):0.95 阈值 + 仅去空白,可能误判 AI 释义之间的"非保护性差异"为冲突
4. **未覆盖的设计盲点**(§7.6.4 新增):当前判定无法区分"云端是手写" vs "云端是本系统上次 AI 版本",未来若做"薄弱词迭代释义"会撞上自己的保护

### 7.1 冲突链路全景

```
[云端有不一致释义] ──→ momo.sync_interpretation 返回 status=2 ──┐
                                                                │
                                                                ▼
                                          worker 写 ai_word_notes.sync_status=2
                                              + match_confidence + match_reason
                                                                │
                                                                ▼
                                          [DB 永久标记为 CONFLICT,无任何自动后续路径]
                                                                │
                                  ┌─────────────────────────────┘
                                  │                             ▼
                          [用户在 SyncStatus 页面看到列表] → 点击"重试冲突"按钮
                                                                │
                                                                ▼
                          retry_conflicts API:把所有 sync_status=2 词重新入队
                          (force_sync=True, 但不重置 sync_status)
                                                                │
                                                                ▼
                          worker 再次调 momo.sync_interpretation
                                                                │
                                                                ▼
                          ⚠️ 如果云端释义未变化,仍返回 status=2,本地状态原地踏步
                          但前端会显示"已重试 N / N 项",给用户"已处理"的错觉
```

**核心矛盾**:墨墨 API 不允许一个 voc_id 创建第二条用户释义 —— 一旦云端先有不一致版本,本系统**无法通过 API 覆盖**。唯一真实解决方式是用户去墨墨 App 手动删除冲突释义,但这点在前端和文档里都没有暗示。

### 7.2 释义匹配算法分析

**位置**:[../../core/maimemo_api.py:276-361](../../core/maimemo_api.py#L276-L361)

判定流程([`_classify_interpretation_list`](../../core/maimemo_api.py#L295)):

1. 拉取云端释义列表
2. 归一化云端释义和本地预期:[`_normalize_interpretation_text`](../../core/maimemo_api.py#L276) = `"".join(text.split())` — **只剥空白字符**
3. 完全匹配 → `status=1, confidence=1.0`
4. 否则计算 `difflib.SequenceMatcher.ratio()`,**阈值 0.95** → `status=1, confidence=ratio`
5. 都不达标 → `status=2, confidence=best_match_ratio`

**潜在误报(把语义一致判为冲突)**:

- ❌ **不剥 markdown / HTML**:本地用 `clean_for_maimemo()` 剥过 markdown 才上传,云端释义来源未知。如果云端有人用了 markdown / HTML(墨墨支持富文本),会被判不一致
- ❌ **不归一标点**:中文逗号 `,` vs 英文 `,`、全角句号 `。` vs 英文 `.`、引号样式 —— 全部贡献差异
- ❌ **大小写敏感**:`SequenceMatcher` 不忽略大小写
- ⚠️ **0.95 阈值对短释义过敏**:例如 `n. 紫色的` vs `n. 紫色`,SequenceMatcher 比率 ≈ 0.80 → 误判冲突

**潜在漏报(把真冲突判为一致)**:

- ⚠️ **剥空白过激**:`"a b c"` 和 `"abc"` 视为相同。对英文释义可能漏报,对中文影响小。

**建议**:

- 实装与 `clean_for_maimemo` 对称的"接收端归一化":剥 markdown、HTML、归一标点、小写化
- 短释义(< 20 字符)阈值放宽到 0.85,或改用字符级 Levenshtein
- 在前端冲突详情里显示 `match_confidence` 和 `match_reason`,让用户能判断是不是误报

### 7.3 问题清单

#### ✅ H3 — `_defer_maimemo_conflict` / `conflict_sync_queue` / `on_conflict` 全是死代码 *(已修复 `d6b0d24`)*

**位置**:[../../core/sync_manager.py:48](../../core/sync_manager.py#L48)、[../../core/sync_manager.py:229-250](../../core/sync_manager.py#L229-L250)、[../../core/sync_manager.py:309](../../core/sync_manager.py#L309)

**事实链条**:

1. `_defer_maimemo_conflict` 只在 worker 取出任务后发现 `current_status == 2` 时触发([../../core/sync_manager.py:309](../../core/sync_manager.py#L309))
2. `current_status` 来自 DB 查询,**只在 `force_sync=False` 时才查询**([../../core/sync_manager.py:298-307](../../core/sync_manager.py#L298-L307))
3. 生产代码所有 4 个 `queue_maimemo_sync` 调用点**全部传 `force_sync=True`**:

   | 调用点 | force_sync | 用途 |
   |---|---|---|
   | [../../core/study_workflow.py:159](../../core/study_workflow.py#L159) | True | 今日任务 |
   | [../../core/study_flow.py:67](../../core/study_flow.py#L67) | True | CLI 启动自愈 |
   | [../../web/backend/user_context.py:255](../../web/backend/user_context.py#L255) | True | Web 启动自愈 |
   | [../../web/backend/routers/sync.py:103](../../web/backend/routers/sync.py#L103) | True | 重试冲突 |

4. 因此 `current_status` 永远是默认值 `0`,永远不命中 `== 2` 分支
5. **结果**:`_defer_maimemo_conflict` 永不触发、`conflict_sync_queue` 永远是空、`on_conflict` 即便注入也永不被调用

**更糟的是**,[../../tests/core/test_sync_manager.py:78-79](../../tests/core/test_sync_manager.py#L78-L79) 把这个怪行为**固化为断言**:

```python
# 注意:根据当前代码实现,API 返回 2 时不会触发 on_conflict,只会记录日志
on_conflict.assert_not_called()
```

测试用 `force_sync=False` 默认值跑出与生产路径不同的行为,等于在测一个生产永不触发的分支。

**影响**:

- 死代码污染:`conflict_sync_queue`、`on_conflict` 参数、`_defer_maimemo_conflict` 方法都是无用代码
- 测试在维护一个错觉,新人读会以为有"冲突队列"这一层机制

**建议**:三选一

- **(A 收敛 — 推荐)**:删除 `conflict_sync_queue`、`on_conflict` 参数、`_defer_maimemo_conflict`、对应测试。前端的"重试冲突"已经够用(虽然作用窄,见 H4)
- **(B 启用)**:让 `retry_conflicts` 用 `force_sync=False`,并实装一个真正的 `on_conflict` 处理器(例如"标记为待用户决策")
- **(C 强化语义)**:retry 前先重置 sync_status=0,让冲突词回到普通同步流程

#### ✅ H4 — "重试冲突"按钮的文案与行为不符(UX 问题,非逻辑 bug) *(短期已修复 `87c7da6`)*

**位置**:[../../web/backend/routers/sync.py:73-116](../../web/backend/routers/sync.py#L73-L116)、[../../web/frontend/src/pages/SyncStatus.tsx:71-79](../../web/frontend/src/pages/SyncStatus.tsx#L71-L79)

**结合 §7.0 设计意图,此项不是逻辑 bug,而是 UI 文案误导**:

- **按钮名**:"重试冲突" 暗示"解决"
- **API 实际行为**:复查云端释义是否仍然冲突(若云端未在墨墨 App 中被修改,什么也不会变)
- **API 返回文案**:`{"retried": N, "total_conflicts": N}`,前端显示 "已重试 N / N 项" → 用户误以为是"已解决 N"

**完整行为链**(供维护参考):

1. `retry_conflicts` 把所有 `sync_status=2` 的词以 `force_sync=True` 重新入队
2. worker 调用 `momo.sync_interpretation` 复查云端
3. 若云端的不一致释义未被用户手动修改 → 仍判 `status=2` → 状态原地踏步
4. **真实解决路径**:用户必须先在**墨墨 App 手动删除冲突释义**,再点重试,此时 `sync_interpretation` 查云端发现空 → 走 create → 成功上传本地版本

这条流程符合"保护用户手动释义"的设计意图。问题只在前端文案/反馈未暗示用户"重试 ≠ 解决"。

**建议**(从轻到重):

- **最低成本**:按钮改名为 **"复查云端状态"** + 加 tooltip:"若云端释义已在墨墨 App 中删除/修改,本次复查会自动同步本地版本。否则仍保留冲突状态。"
- **更好**:API 返回区分 `still_conflict_count`(本次复查后仍冲突)和 `resolved_count`(本次复查后解决);前端区分显示 "复查 N 项 / 解决 X / 仍冲突 Y"
- **理想**:UI 增加"云端释义 vs 本地释义"对比 + 一键复制本地释义到剪贴板(便于用户去墨墨贴上去 / 删除冲突)

#### 🟡 M4 — 释义匹配算法可能误报冲突

详细分析见 [§7.2](#72-释义匹配算法分析)。

**建议**:

- 对称归一化(剥 markdown / HTML / 标点 / 大小写)
- 短释义阈值放宽
- 前端暴露 `match_confidence` 让用户判别

#### 🟢 L4 — `match_confidence` / `match_reason` 写入但前端不用

**位置**:[../../web/frontend/src/pages/SyncStatus.tsx:103-115](../../web/frontend/src/pages/SyncStatus.tsx#L103-L115)

冲突表格只显示:单词、释义、创建时间。`match_confidence`(数据库有、API 返回)和 `match_reason` 都未展示。

**建议**:冲突表格补两列"匹配度"和"差异原因"

#### 🟢 L5 — 冲突解决路径无任何文档

[../../docs/dev/AUTO_SYNC.md:113-149](../../docs/dev/AUTO_SYNC.md#L113-L149) 提到了 `sync_status=2` 的产生条件,但没说怎么解决。

**建议**:在 `AUTO_SYNC.md` 加一节"如何解决冲突释义"

### 7.4 状态机自洽性(冲突维度)

- **状态值 `sync_status=2` 的写入路径只有 1 处**:[../../core/sync_manager.py:393-411](../../core/sync_manager.py#L393-L411) worker 处理 API 返回 status=2 时写
- **`sync_status=2` 的读出路径有 3 处**:`_classify_interpretation_list`(判定)、`process_word_list` 跳过分支(显示 sync_conflict)、`list_by_state(CONFLICT)`(SyncStatus 列表)
- **状态出口**:`retry_conflicts` 重新入队 → 若云端无变化则原地踏步;若云端被用户在墨墨修改/删除 → 走正常流程被覆盖为 1
- **关于"无自动复位路径"**:从 `sync_status=2` 没有任何代码路径回到 `sync_status=0`——结合 §7.0 的设计意图,这是**有意为之**:冲突信号不应被系统单方面清除,只有"云端释义被改"才是合法的解除条件,而这只能通过 `retry_conflicts` + worker 调 momo API 复查来发现

冲突状态机本身**封闭且收敛**,且符合"保护用户手动释义"的设计意图。续审保留的 H3 是死代码污染(可清理)、H4 是文案误导(可改名)、M4 是判定算法可能误报(可调归一化)—— 这三处都不动状态机本体,仅是周边治理。

### 7.5 冲突相关修复顺序

| 优先级 | 修复 | 工作量 | 风险 | 状态 |
|---|---|---|---|---|
| 🔴 必修 | **H3 (A) 方案**:删除死代码三件套(`conflict_sync_queue` + `on_conflict` + `_defer_maimemo_conflict`)+ 修正测试 | 小 | 低(全是无用代码) | ✅ `d6b0d24` |
| 🟡 建议 | **H4 短期**:按钮改名 "复查云端状态" + tooltip 说明真实解决路径 | 小 | 低 | ✅ `87c7da6` |
| 🟡 建议 | **M4**:匹配算法对称归一化(剥 markdown/HTML/标点/大小写) | 中 | 中 | ✅ 已完成 |
| 🟢 可选 | **H4 中期**:API 返回 `still_conflict_count` + 前端区分显示 | 小 | 低 | ✅ 已完成 |
| 🟢 可选 | **L4**:前端冲突表格补 `match_confidence` / `match_reason` 列 | 小 | 低 | ✅ 已完成 |
| 🟢 可选 | **L5**:文档补"如何解决冲突释义" | 小 | 低 | ✅ 已完成 |

### 7.6 留给用户拍板的设计问题(冲突部分)

#### 7.6.1 真冲突时,本地是否有权"强推"覆盖云端?

- **当前**:无,墨墨 API 不允许一个 voc_id 第二条释义
- **备选**:在 `sync_interpretation` 里增加 `force_overwrite=True` 路径 → 先 `delete_interpretation`(删云端) → 再 `create`
- **风险**:可能误删其他场景的释义(如词本协作);需要在 UI 明确二次确认

#### 7.6.2 冲突词是否参与 AI 迭代?

- **当前**:冲突词在 `partition_by_processability` 被分到 processed,跳过 AI;但 `query_weak_words` 仍可能把它列为薄弱候选
- **备选**:把冲突词从迭代候选池剔除,避免对一个"无法上传"的词反复消耗 AI token

#### 7.6.3 `force_sync=True` 是否应该成为默认行为?

- **当前**:4 个调用点全部显式传 True;`force_sync=False` 在生产路径中无任何调用方
- **备选**:把 `queue_maimemo_sync` 的 `force_sync` 默认改为 True,或干脆删除该参数,简化接口

#### 7.6.4 是否引入 `last_synced_content` 字段做 3-way 区分?

**问题**:当前冲突判定只看"云端 vs 本地"两侧文本相似度,无法区分以下两种情况:

- 云端释义是**用户在墨墨手写的** → 应保护(当前的设计意图)
- 云端释义是**本系统上次 AI 同步的旧版本** → 应允许覆盖

**会咬人的场景**:

1. **prompt 改版**:新 prompt 生成的释义与旧 prompt 不同 → 误报冲突
2. **切换 AI 提供商**(Gemini ↔ Mimo):释义风格差异 → 误报冲突
3. **未来"薄弱词迭代重炼释义"**(目前 `iteration_manager` 只动 `memory_aid` 不动 `interpretation`,但已被预想到):新版 AI 释义 100% 会撞上自己之前的版本

**设计方案**:经典 3-way merge

在 `ai_word_notes` 加字段 `last_synced_content`(或 hash),记录上次成功同步到云端的释义文本。判定逻辑改为:

| 云端释义 vs 本地 | 云端 vs `last_synced` | 判定 |
|---|---|---|
| 一致 | — | `status=1`(已同步) |
| 不一致 | 云端 ≈ `last_synced` | **本系统旧 AI 版本** → 调 `update_interpretation` 覆盖,`status=1` |
| 不一致 | 云端 ≠ `last_synced` | **被外部(墨墨手动)修改过** → `status=2` 保留(保护意图生效) |
| 云端无 | `last_synced` 有 | 用户在墨墨手动删除过 → create,`status=1` |
| 云端无 | `last_synced` 无 | 首次同步 → create,`status=1` |

**前置依赖**:墨墨 API 是否提供 `update_interpretation`?——已确认存在([../../core/maimemo_api.py:381](../../core/maimemo_api.py#L381) `update_interpretation`),所以技术上可行。

**成本**:

- Schema:加 1 列(`ALTER TABLE ai_word_notes ADD COLUMN last_synced_content TEXT`)
- 逻辑:`sync_interpretation` 增加比对分支 + 成功同步后回写 `last_synced_content`
- 历史数据迁移:已有 `sync_status=1` 的词,把当前 `basic_meanings` 写入 `last_synced_content` 作为 baseline(等同于"信任已同步的内容是本系统贡献的")

**优先级判断**:

- **目前不必修**:现状对"保护手写"足够,prompt/provider 切换不频繁,迭代释义未实装
- **触发修复的明确信号**:出现 §7.6.4 的"咬人场景"任一,或决定实装"薄弱词迭代重炼释义"功能时,此项立刻升级为必修

---

## 8. 查重逻辑专项审查 (续审 2)

> **触发**:延伸审查"今日任务"链路的查重环节(`partition_by_processability` 三表兜底)
> **续审日期**:2026-05-14(同日)
> **聚焦**:三表查重的正确性、与 `enrich_with_states` 的关系、性能开销、边界场景

### 8.1 查重链路全景

```
study_workflow.process_word_list
        │
        ▼
[1] normalize_cloud_items     脏数据过滤(缺 voc_id / spelling)
        │
        ▼
[2] enrich_with_states        计算每个词的 WordState (5 态)
        │                       查询: LEFT JOIN processed_words + ai_word_notes (UNION 两段)
        │                       副作用: 异步入队 backfill_processed (如发现历史漏标)
        ▼
[3] partition_by_processability   分组 unprocessed / processed
        │                       查询 1: filter_unprocessed (processed_words ∪ ai_word_notes)
        │                       查询 2: _get_tracked_ids (word_progress_history)
        │                       查询 3: _get_ids_with_local_notes (ai_word_notes 内容)
        │                       副作用: 又一次异步入队 backfill_processed
        ▼
pending_items, processed_items
```

**核心观察**:[2] 和 [3] **互不相干** —— [2] 计算出的 `WordState` 完全被丢弃,[3] 又从零开始查 3 张表。这是事实层面的重复劳动。

[../../core/study_workflow.py:194-195](../../core/study_workflow.py#L194-L195) 印证:

```python
enriched = self.word_service.enrich_with_states(normalized_items, auto_backfill=True)
pending_items, processed_items = self.word_service.partition_by_processability(
    [item for item, _ in enriched]   # ⚠️ WordState 部分被直接丢弃
)
```

### 8.2 查重真值表(应判 vs 实际判)

设一个词 W 在本地 3 张表的"出现"状态如下表。横向是各表存在性,纵向是各表组合:

| processed_words | ai_word_notes (有内容) | word_progress_history | 应判定 | partition 实际判定 |
|---|---|---|---|---|
| ✓ | ✓ | * | processed | ✅ processed (笔记自愈命中) |
| ✓ | ✓ 但内容字段全空 | * | processed | ⚠️ **遗漏**(`filter_unprocessed` 不判 NOT_STARTED,`_get_ids_with_local_notes` 又因"内容空"排除) |
| ✓ | ✗ | * | processed | 🔴 **遗漏**(只在 processed_words,3 套兜底全不命中) |
| ✗ | ✓(有内容) | * | processed | ✅ processed (笔记自愈 + backfill) |
| ✗ | ✓(内容空) | * | ? | ❌ unprocessed(被 AI 重新生成) |
| ✗ | ✗ | ✓ | ? | ⚠️ processed(progress 兜底命中,但 word_progress_history 已是无写入死表) |
| ✗ | ✗ | ✗ | unprocessed | ✅ unprocessed |

**红色重点行**:**只在 `processed_words`、没有 `ai_word_notes` 的词**会被 `partition_by_processability` **静默丢弃** —— 既不进 `unprocessed` 也不进 `processed`,在 `process_word_list` 中完全消失(`skipped_spells` 列表也没有它)。

**谁会创造这种数据?**

- **DRY_RUN 路径**:[../../core/study_workflow.py:145-151](../../core/study_workflow.py#L145-L151) `mark_completed` 只调 `mark_processed_batch`,写 `processed_words` **不写 `ai_word_notes`**
- 手动写过 `processed_words`(脚本调试 / 数据修复)
- 旧版本数据迁移残留

**对比 `enrich_with_states` 的判定**:同样的词在 `derive_state(processed=True, sync_status=None)` 下会被判为 `LOCAL_READY` —— 即"已处理"。这与 `partition` 的结果**不一致**。

### 8.3 问题清单

#### ✅ M5 — `partition_by_processability` 与 `enrich_with_states` 重复劳动,且边界场景静默丢词 *(已修复 `8282bd0`)*

**位置**:[../../core/word_service.py:104-159](../../core/word_service.py#L104-L159)、[../../core/study_workflow.py:194-195](../../core/study_workflow.py#L194-L195)

**事实**:

1. `enrich_with_states` 已经用 LEFT JOIN UNION 算出每个词的 `WordState`(5 态),`derive_state(processed=True, sync_status=None) → LOCAL_READY` 已经正确覆盖"只在 processed_words"的边界
2. 但调用方丢弃了 `WordState`,只把 item 列表传给 `partition_by_processability`
3. `partition` 重新查 3 张表,且**没有像 `derive_state` 那样**覆盖"只在 processed_words"的情况
4. 现有测试 [../../tests/core/test_word_service.py:137-222](../../tests/core/test_word_service.py#L137-L222) **没覆盖这条边界 case**(全部 mock 三个 helper 函数,等于在测胶水代码,不是测真值表)

**症状**:DRY_RUN 跑过一次后切到正式模式,这些词会**消失** —— 既不调 AI,也不显示状态。

**建议**:重写为基于 `WordState` 分组(见 §8.4)。

#### 🟡 M6 — `_get_ids_with_local_notes` 中 `is_processed(voc_id)` 触发 N+1 查询

**位置**:[../../core/word_service.py:275-290](../../core/word_service.py#L275-L290)

```python
for voc_id in candidate_ids:
    note = notes_map.get(voc_id)
    ...
    if has_content:
        ids_with_notes.add(voc_id)
        if not is_processed(voc_id):   # ⚠️ N+1
            to_backfill.append(voc_id)
```

`is_processed` 是单条查询([../../database/progress_repo.py:74-77](../../database/progress_repo.py#L74-L77))。100 个候选词触发 100 次单点 SELECT。

**修复**:循环外一次批量查:

```python
processed_ids = get_processed_ids_in_batch(list(candidate_ids))
for voc_id in candidate_ids:
    ...
    if has_content:
        ids_with_notes.add(voc_id)
        if voc_id not in processed_ids:
            to_backfill.append(voc_id)
```

若按 §8.4 重写 partition,这个函数整体可以删除,M6 自然消失。

#### 🟡 M7 — `auto_backfill` 在同一次 `process_word_list` 内被触发 2 次

`enrich_with_states(auto_backfill=True)` 触发一次 `_enqueue_backfill_processed`,接着 `partition_by_processability` 内部的 `_get_ids_with_local_notes` 又触发一次。两次入队的集合高度重叠("有笔记但 `processed_words` 没记录"的子集)。

写队列是 idempotent(`INSERT OR REPLACE`),不会写错数据,但浪费写队列调度槽 + 日志噪音 + 重复入队的对应写锁机会。

**修复**:重构后只在 `enrich_with_states` 触发,partition 不独立 backfill。

#### 🟢 L6 — `partition_by_processability` 异常降级到"全 unprocessed",雪崩式成本

**位置**:[../../core/word_service.py:153-159](../../core/word_service.py#L153-L159)

```python
except Exception as e:
    self.logger.error(f"[partition_by_processability] 分组失败: {e}")
    return items, []   # 全部当待处理
```

数据库瞬时故障 → 全部 N 词被判 unprocessed → 1500 词全部重新调 AI → 估算 1500 × 100 token ≈ 15 万 token 浪费。

**建议**:

- **保守降级**:`return [], items`(全部当 processed,跳过 AI)
- **明示降级**:抛异常,让 `process_word_list` 决定是否继续

#### 🟢 L7 — `normalize_cloud_items` 静默丢弃脏数据,前端无感知

**位置**:[../../core/word_service.py:53-66](../../core/word_service.py#L53-L66)

脏数据(无 `voc_id` 或 `spelling`)只记 warning 日志,不向前端报告丢弃数量。100 词 → 95 词处理时,前端进度条分母变成 95,与用户入口看到的"今日 100 词"对不上。

**建议**:`normalize_cloud_items` 返回 `(items, dropped_count)`,在 progress 事件里附带显示。

#### 🟢 L8 — `_get_tracked_ids` 兜底的 `word_progress_history` 语义存疑(同原 H2)

已在原审查 §2 H2 提及。本节再次确认:**在 §8.4 重写后**,这层兜底彻底消失,因为 `derive_state` 不依赖 `word_progress_history`。

### 8.4 推荐重写:把查重折叠到 WordState

```python
def partition_by_processability(self, items: List[WordItem]) -> Tuple[List[WordItem], List[WordItem]]:
    if not items:
        return [], []

    try:
        enriched = self.enrich_with_states(items, auto_backfill=True)
        unprocessed: List[WordItem] = []
        processed: List[WordItem] = []
        for item, state in enriched:
            if state == WordState.NOT_STARTED:
                unprocessed.append(item)
            else:
                processed.append(item)
        return unprocessed, processed
    except Exception as e:
        self.logger.error(f"[partition_by_processability] 分组失败: {e}")
        return [], items   # 保守降级:不调 AI(L6 修复)
```

**收益对比**:

| 维度 | 当前 | 重写后 |
|---|---|---|
| DB 查询次数 | 4(enrich 2 段 UNION + partition 3 段 IN) | 2(enrich 单次 LEFT JOIN UNION) |
| backfill 触发次数 | 2 | 1 |
| DRY_RUN 词遗漏 | 🔴 是 | ✅ 修复(LOCAL_READY → processed) |
| 内容空笔记词遗漏 | ⚠️ 是 | ✅ 修复(LOCAL_READY 不看内容) |
| 异常降级成本 | 1500 词 × AI | 0 |
| word_progress_history 死兜底 | 仍占代码体积 | 完全移除 |
| N+1 | 是 | 否 |
| 行数 | 47 行 + 2 helper(58 行) | 12 行 |

**调用方简化**:[../../core/study_workflow.py:194-195](../../core/study_workflow.py#L194-L195) 不再需要单独调 `enrich_with_states`(partition 内部已调),可省一层。

**风险点**:

把"有笔记但内容全空"的词从 `unprocessed` 移到 `processed`,**会少调一些 AI**。需要判断这是好事还是坏事(详见 §8.6.1)。

### 8.5 修复优先级

| 优先级 | 修复 | 工作量 | 风险 | 状态 |
|---|---|---|---|---|
| 🟡 建议 | **M5 + M6 + M7 合并修复**:partition 重写为 WordState 分组,删除 `_get_tracked_ids` / `_get_ids_with_local_notes` / 内部 N+1 | 中(改 word_service.py + 同步测试) | 中(行为细微变化,需回归 DRY_RUN 与空笔记场景) | ✅ `8282bd0` |
| 🟢 可选 | **L6**:降级路径改为 `return [], items` 或抛异常 | 极小 | 低 | ✅ 已在 M5 重写中一并解决 |
| 🟢 可选 | **L7**:`normalize_cloud_items` 返回 `dropped_count`,progress 事件展示 | 小 | 低 | ✅ 已完成 |

注:**M5 重写会同时解决 M6 / M7 / L8**,所以建议一次合并改造,不要分批改。

### 8.6 留拍板的设计问题

#### 8.6.1 "有笔记但内容字段全空"的词应如何处理?

- **方案 A**(重写后默认):当作 LOCAL_READY 跳过 AI,信任已经调用过,防反复消耗 token
- **方案 B**:重新调 AI(把内容空当作"上次失败,该重做"的信号)
- **方案 C**(治本):在 `save_ai_word_notes_batch` 加 schema 校验,拒绝写入字段全空记录,根本上避免该数据

**建议**:**C(治本)+ A(治标)** 组合。但需要确认"全空"在生产中的实际频率(可能根本不发生,只是理论边界)。

#### 8.6.2 异常降级应该走"全 unprocessed"(浪费)还是"全 processed"(保守跳过)?

- **当前**:`return items, []` → 雪崩式重调 AI
- **建议**:`return [], items` → 至少不浪费,用户下次自然重试
- **反对意见**:若降级是因数据库**全空**(新设备首次跑),全 processed 会永远跳过 AI

新设备首次跑场景:`filter_unprocessed` 不会异常,而是返回所有 voc_id 都不在表中 → 全部 NOT_STARTED → 正常处理。所以"全空"不会触发 except 分支,反对意见不成立。

#### 8.6.3 DRY_RUN 标记的词,在正式模式下应该重新处理还是跳过?

- **方案 A**(M5 重写后):跳过(信任 dry_run 已经验证过)
- **方案 B**:重新处理(dry_run 字面意义是"试运行不落地",正式模式应该重做)

方案 B 更符合 dry_run 的字面语义,但当前实现把 dry_run 和正式 mixed 写入同一张 `processed_words`,无法区分 —— 需要给 `processed_words` 加 `dry_run BOOLEAN` 字段,partition 时排除。

**建议**:**短期方案 A**(M5 重写后自然行为,把 dry_run 视为"已验证");**长期方案 B**(若实际场景里有"先 dry_run 试错再正式跑"的需求)。

---

## 9. 审查附录:核心文件索引

| 功能 | 文件路径 | 关键函数 | 行号 |
|---|---|---|---|
| 今日任务编排(CLI) | [../../core/study_flow.py](../../core/study_flow.py) | `StudyFlowManager.run` | 76-122 |
| 今日任务编排(Web) | [../../web/backend/routers/study.py](../../web/backend/routers/study.py) | `process_today` | 281-318 |
| 单词处理流水线 | [../../core/study_workflow.py](../../core/study_workflow.py) | `StudyWorkflow.process_word_list` | 176-315 |
| 单词业务服务层 | [../../core/word_service.py](../../core/word_service.py) | `partition_by_processability` | 104-150 |
| 5 态状态机 | [../../database/word_state.py](../../database/word_state.py) | `WordState` / `derive_state` | 21-54 |
| Momo API 封装 | [../../core/maimemo_api.py](../../core/maimemo_api.py) | `sync_interpretation` / `get_today_items` | 398 / 662 |
| 后台同步调度 | [../../core/sync_manager.py](../../core/sync_manager.py) | `_maimemo_sync_worker` | 252-510 |
| 笔记持久化 | [../../database/notes_repo.py](../../database/notes_repo.py) | `save_ai_word_notes_batch` / `set_note_sync_status` | 182 / 279 |
| 单词状态查询 | [../../database/word_repo.py](../../database/word_repo.py) | `get_word_states_in_batch` / `filter_unprocessed` | 64 / 106 |
| 进度仓库 | [../../database/progress_repo.py](../../database/progress_repo.py) | `mark_processed_batch` / `log_progress_snapshots` | 97 / 122 |

---

*本报告以当时(2026-05-14)的代码快照为准,后续修复后内容可能过期。如需重新审查,请重新对照 commit。*
