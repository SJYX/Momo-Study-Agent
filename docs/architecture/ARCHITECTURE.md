# 系统架构（ARCHITECTURE）

> 本文是 `docs/architecture/` 的单一入口。前身为 `OVERVIEW.md` + `SYSTEM_ARCHITECTURE.md` + `DATA_FLOW.md` 三份独立文档，2026-04-21 合并。
>
> - 规则/MUST 清单：[`../dev/AI_CONTEXT.md`](../dev/AI_CONTEXT.md)
> - 数据库表结构：[`DATABASE_DESIGN.md`](DATABASE_DESIGN.md)
> - 启动分支决策：[`decision_flow.md`](decision_flow.md)
> - 日志系统：[`LOG_SYSTEM.md`](LOG_SYSTEM.md) 和 [`../dev/LOGGING.md`](../dev/LOGGING.md)
> - 运行期 WAL/游标铁律：[`../../database/README.md`](../../database/README.md)

## 1. 系统定位

Momo Study Agent 是一个基于墨墨背单词 OpenAPI 的**多用户 AI 助记工具**：拉取今日/未来词汇 → 调 LLM 生成助记 → 写回墨墨 → 本地 SQLite 持久化 + Turso 云端同步。

- 主入口：CLI（`python main.py`）；Web 前端已集成到 main 分支（后端 FastAPI + 前端 React SPA，启动方式 `python -m web.backend --user <name>` 或 `python scripts/start_web.py`）。
- 运行形态：单进程（进程锁防多开），多用户 profile 隔离，离线可用（云端缺失时降级为纯本地）。

## 2. 模块地图

| 层 | 文件 | 职责 |
| --- | --- | --- |
| 入口 | `main.py` | 进程锁、配置引导、菜单路由、退出收尾 |
| 配置 | `config.py` | 简化导出层（路径常量、bootstrap 调用、Settings 导出、switch_user 包装） |
| 配置（新） | `core/profile_loader.py` | 三阶段 env 加载、用户规范化、DB 路径解析（Phase 6.3a） |
| 配置（新） | `core/settings.py` | pydantic BaseSettings 配置模型、字段校验、缓存管理（Phase 6.3b） |
| 特性开关（新） | `core/feature_flags.py` | Kill Switch 框架：AUTO_WARMUP_SYNC_ENABLED / SYNC_STATUS_HEAVY_QUERY_ENABLED / BACKGROUND_RETRY_ENABLED（Phase 6.1） |
| UI | `core/ui_manager.py` | CLI 终端交互与状态呈现（仅 I/O，无业务） |
| 向导 | `core/config_wizard.py` | 首次配置、凭证校验（`validate_momo/mimo/gemini`） |
| Profile | `core/profile_manager.py` | 多账号管理、用户选择 |
| Profile 追踪（新） | `core/active_profile_registry.py` | 进程级活跃 profile 追踪（Web 多用户场景下对 P3+ 同步的暂停控制，Phase 4） |
| 业务总线 | `core/study_workflow.py` | 任务过滤、AI 并发调度、批量落库投递、Priority.P1 注入 |
| 迭代引擎 | `core/iteration_manager.py` | 薄弱词选优与强力重炼（`it_level` 分级） |
| 薄弱词筛选 | `core/weak_word_filter.py` | 多维评分（熟悉度/复习/时间/迭代）+ 动态阈值、动态 `_config.DB_PATH` 读取 |
| 墨墨 API | `core/maimemo_api.py` | 墨墨 OpenAPI 封装、`threading.Lock` 保护的频控 |
| AI 客户端 | `core/gemini_client.py` / `core/mimo_client.py` | LLM 调用、结果清洗、`requests.Session` 复用 |
| 后台同步 | `core/sync_manager.py` | PriorityQueue（P1/P2/P3/P4）、防饿死保底、活跃 profile 暂停、冲突回写（Phase 4） |
| 优先级（新） | `core/sync_priority.py` | Priority IntEnum：P1(1) 今日 / P2(2) 主动 / P3(3) warmup / P4(4) 预留（Phase 4） |
| 持久层 | `database/connection.py` | 单例连接管理、写队列、后台写/同步守护线程、动态 `_config.DB_PATH` |
| 持久层（新） | `database/backends/` | Turso 后端适配层（`pyturso` 优先，`libsql` 回退），统一 `connect/do_sync_on/op_lock_for/should_close` 协议 |
| 持久层 | `database/momo_words.py` | 主库业务 SQL、`sync_databases()` / `sync_hub_databases()` |
| 持久层 | `database/hub_users.py` | Hub 用户元数据与加密凭据 |
| 持久层 | `database/schema.py` | 建表、schema 迁移调用、migration 执行 |
| 持久层（新） | `database/migrations/runner.py` | PRAGMA user_version 迁移编排、顺序应用、事务管理（Phase 6.2） |
| 持久层（新） | `database/migrations/V001_initial.py` | 历史 ALTER 语句收纳、幂等性检查、数据回填（Phase 6.2） |
| 持久层 | `database/utils.py` | 加密、时区时间戳、错误分类、动态 `_config.DB_PATH` |
| 日志 | `core/logger.py` + `core/log_config.py` | 结构化 JSON、异步写入、性能统计、ContextLogger 节流方法（Phase 5） |
| 体检 | `tools/preflight_check.py` | 启动前连通性 + 凭据校验（text/json 双输出） |

## 3. 主流程数据流

### 3.1 今日任务 / 未来计划

```
[主线程]
  MaiMemoAPI.get_today_items() 或 query_study_records()
  └→ StudyWorkflow.process_word_list(words, label)
      ├→ database.momo_words.get_processed_ids_in_batch()      # 去重过滤
      ├→ ThreadPoolExecutor(max=AI_PIPELINE_WORKERS)
      │     └→ ai_client.generate_mnemonics(batch)
      ├→ database.momo_words.save_ai_word_notes_batch()         # 入写队列，sync_status=0
      └→ SyncManager.queue_maimemo_sync(force_sync=True)        # 入墨墨同步队列

====================== 异步边界 ======================

[后台写守护线程]（database/connection.py::_writer_daemon）
  消费写队列 → 批量 commit → WAL 冲突退避重试

[墨墨同步 worker 线程]（sync_manager.py::_maimemo_sync_worker）
  消费队列 → MaiMemoAPI.sync_interpretation(force_create=True)
  └→ sync_status: 0 → 1（成功）或 2（冲突）

[云端同步守护线程]（database/connection.py::_sync_daemon）
  debounce → gc.collect() → conn.sync() 把本地 WAL 帧推到 Turso
```

### 3.2 智能迭代

```
IterationManager.run_iteration()
  └→ WeakWordFilter.get_weak_words_by_score(min_score=50)
      └→ Fallback: by_category(threshold) → _get_weak_words_from_db()
  分级处理:
    it_level == 0 → _handle_level_1_selection()  # 从现有助记选优 + 同步
    it_level > 0  → _handle_level_2_refinement() # 强力重炼
  追加薄弱词到云词本 "MomoAgent: 薄弱词攻坚"
```

## 4. 并发模型与优先级调度

> 从高并发事故里沉淀的读写分离架构。详见 [`../../database/README.md`](../../database/README.md#runtime-iron-rules运行期铁律) 的运行期铁律小节。

### 4.1 基础读写分离

```
业务线程（多）
   ├→ 读路径 → ThreadLocal 读连接（本地 SQLite 副本）
   └→ 写路径 → PriorityQueue(maxsize=10000)  # Phase 4 升级
                    ↓ (priority, seq, payload)
              [后台写守护线程（单）]
                    ↓
              Turso backend 写连接（单例）
                    ↓
              本地副本 .db 文件 + WAL
                    ↓
        [云同步守护线程] debounce → backend.do_sync_on(conn)
                    ↓
              云端 Turso 主库
```

### 4.2 同步优先级队列（Phase 4）

```
SyncManager.queue_maimemo_sync(profile_name, priority=Priority.P1, ...)
    │
    ├─ Priority.P1 (value=1)  → 今日任务、study_workflow 队列
    ├─ Priority.P2 (value=2)  → 用户主动点击（sync.py retry_conflicts）
    ├─ Priority.P3 (value=3)  → warmup 自动补偿（user_context _warmup_async）
    └─ Priority.P4 (value=4)  → 预留

队列管理逻辑：
  • 全局单一消费者 worker 线程循环 queue.get(timeout=5)
  • PriorityQueue 自动按 priority 排序（小值优先）
  • 防饿死保底：连续 5 个 P1 后强制轮转非 P1 任务
  • 活跃 profile 检查：P3+ 非活跃时暂停，等到 ActiveProfileRegistry.is_active() = true
```

### 4.3 活跃 Profile 追踪（Phase 4）

```
Web 多用户场景：
  web/backend/deps.py::_resolve_profile()
  └→ ActiveProfileRegistry.set_active(profile_name)
  
SyncManager._maimemo_sync_worker()
  对每个任务检查：
    if task.priority >= Priority.P3:  # P3 及以上才做检查
      if not ActiveProfileRegistry.is_active(task.profile_name):
        queue.put(task)  # 放回队列等待
        continue
  
效果：Web 场景下只有当前活跃用户的 warmup 同步运行，其他用户的 P3 暂停
```

**三条铁律：**

1. **进程唯一**：`data/.process.lock` 物理锁拦截多进程。
2. **连接单例**：同一数据库文件只持有一个写连接单例（main/hub 各自单例）。
3. **游标必闭**：所有 `SELECT` 必须 `try/finally + cur.close()`；避免长时间占用导致写入/同步受阻。

## 5. 数据同步模型（Turso Backend 抽象）

**原理**：`database/backends/` 提供统一后端接口，运行时自动选择 `pyturso`（优先）或 `libsql`（回退）。

- `pyturso`：`turso.sync.connect(...)`，同步周期使用 `push/pull/checkpoint`。
- `libsql`：`libsql.connect(...)`，同步周期使用 `conn.sync()`。
- 上层统一调用 `backend.do_sync_on(conn)`，不直接绑定具体驱动 API。

**执行路径：**

- `sync_databases()` / `sync_hub_databases()`（`database/sync_service.py`，由 `database/momo_words.py` re-export）：唯一合法的同步入口，内部统一走 `backend.do_sync_on(conn)`。
- **前台同步**：用户交互触发，通过 `progress_callback` 回调渲染 CLI 进度条。
- **后台同步**：菜单任务完成、退出收尾、定时 debounce 触发，仅写阶段日志（INFO/WARNING），不干扰交互。

**降级策略：**

- 无 `TURSO_DB_URL` / `TURSO_AUTH_TOKEN` 或 Turso 后端不可用（`pyturso` 与 `libsql` 都不可用）→ 自动退回纯本地 sqlite3 模式。
- `FORCE_CLOUD_MODE=True` 时，若云端不通会提供三选项：立即补配置 / 本次会话临时降级 / 退出并打印修复清单。

## 6. 外部依赖

| 依赖 | 用途 | 封装点 |
| --- | --- | --- |
| 墨墨 OpenAPI | 今日/未来任务、释义/助记/例句/云词本 CRUD | `core/maimemo_api.py`（含 10s/20 次 + 60s/40 次自适应限流、Bearer 认证） |
| Turso (`pyturso` / `libsql`) | 云端备份、多设备同步 | `database/backends/` + `database/sync_service.py` |
| Gemini | AI 助记生成 | `core/gemini_client.py`（`google-genai` SDK） |
| 小米 Mimo | AI 助记生成（备选） | `core/mimo_client.py`（HTTP + `requests.Session`） |
| 中央 Hub | 多用户元数据、加密凭据、审计日志 | `database/hub_users.py`（Fernet 加密） |

## 7. 同步状态与 WordState

`ai_word_notes.sync_status` 字段用于同步细分状态；Web/业务层统一通过 `database/word_state.py` 的 `WordState`（5 态）展示。

`sync_status` 字段语义（**只反映"当前用户对该单词的云端释义同步状态"，与内容来源无关**）：

| 值 | 含义 |
| --- | --- |
| `0` | 云端未检出自己的释义 |
| `1` | 云端释义与本地一致 |
| `2` | 云端释义存在，但与本地内容不一致（冲突） |
| `5` | 同步失败（如非法资源 ID 等不可重试场景） |

状态流转细节（初始化规则 / 内存信任快路径 / 冲突处理）见 [`../dev/AUTO_SYNC.md`](../dev/AUTO_SYNC.md)、[`DATABASE_DESIGN.md`](DATABASE_DESIGN.md) 与 `database/word_state.py`。

## 8. 关键运行规则

- **AI 提供商切换**：`AI_PROVIDER=mimo|gemini`（默认 `mimo`）。
- **批量大小**：`BATCH_SIZE`（默认 `1`，按实际 AI 并发与上下文限制调整）。
- **AI 并发**：`AI_PIPELINE_WORKERS`（默认 `2`）。
- **时间戳**：统一 ISO 8601 带时区（`get_timestamp_with_tz()` in `database/utils.py`）。
- **用户身份**：`username.strip().lower()` 统一规范化。
- **主菜单**：`1` 今日任务 / `2` 未来计划 / `3` 智能迭代 / `4` 同步并退出。
