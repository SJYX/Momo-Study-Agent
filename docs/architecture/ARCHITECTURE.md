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

- 主入口：CLI（`python main.py`）；Web 前端初版在 `feat/web-ui` 分支（方案见 `../dev/WEB_UI_PLAN.md`）。
- 运行形态：单进程（进程锁防多开），多用户 profile 隔离，离线可用（云端缺失时降级为纯本地）。

## 2. 模块地图

| 层 | 文件 | 职责 |
| --- | --- | --- |
| 入口 | `main.py` | 进程锁、配置引导、菜单路由、退出收尾 |
| 配置 | `config.py` | 路径、用户 profile、全局配置加载 |
| UI | `core/ui_manager.py` | CLI 终端交互与状态呈现（仅 I/O，无业务） |
| 向导 | `core/config_wizard.py` | 首次配置、凭证校验（`validate_momo/mimo/gemini`） |
| Profile | `core/profile_manager.py` | 多账号管理、用户选择 |
| 业务总线 | `core/study_workflow.py` | 任务过滤、AI 并发调度、批量落库投递 |
| 迭代引擎 | `core/iteration_manager.py` | 薄弱词选优与强力重炼（`it_level` 分级） |
| 薄弱词筛选 | `core/weak_word_filter.py` | 多维评分（熟悉度/复习/时间/迭代）+ 动态阈值 |
| 墨墨 API | `core/maimemo_api.py` | 墨墨 OpenAPI 封装、`threading.Lock` 保护的频控 |
| AI 客户端 | `core/gemini_client.py` / `core/mimo_client.py` | LLM 调用、结果清洗、`requests.Session` 复用 |
| 后台同步 | `core/sync_manager.py` | 墨墨释义同步队列、冲突回写 |
| 持久层 | `database/connection.py` | Embedded Replica 单例连接、写队列、后台写/同步守护线程 |
| 持久层 | `database/momo_words.py` | 主库业务 SQL、`sync_databases()` / `sync_hub_databases()` |
| 持久层 | `database/hub_users.py` | Hub 用户元数据与加密凭据 |
| 持久层 | `database/schema.py` | 建表、`ALTER TABLE` 平滑升级、Hub 初始化 |
| 持久层 | `database/utils.py` | 加密、时区时间戳、错误分类 |
| 持久层（可选门面）| `database/legacy.py` | `from database.legacy import X` 作为老 `core.db_manager` 调用点的过渡 drop-in（re-export 所有子模块） |
| 日志 | `core/logger.py` + `core/log_config.py` | 结构化 JSON、异步写入、性能统计 |
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

## 4. 并发模型

> 从高并发事故里沉淀的读写分离架构。详见 [`../../database/README.md`](../../database/README.md#runtime-iron-rules运行期铁律) 的运行期铁律小节。

```
业务线程（多）
   ├→ 读路径 → ThreadLocal 读连接（本地 SQLite 副本）
   └→ 写路径 → 写队列 Queue(maxsize=10000)
                    ↓
              [后台写守护线程（单）]
                    ↓
              Embedded Replica 写连接（单例）
                    ↓
              本地副本 .db 文件 + WAL
                    ↓
        [云同步守护线程] debounce → conn.sync()
                    ↓
              云端 Turso 主库
```

**三条铁律：**

1. **进程唯一**：`data/.process.lock` 物理锁拦截多进程。
2. **连接单例**：同一 replica 文件全局只持有一个 `libsql` 连接对象。
3. **游标必闭**：所有 `SELECT` 必须 `try/finally + cur.close() + c.commit()`，否则锁死 WAL 阻塞 `conn.sync()`。

## 5. 数据同步模型（libsql Embedded Replicas）

**原理**：`libsql.connect(path, sync_url, auth_token)` 返回的连接**同时管理本地 SQLite 文件和远程 Turso 主库**——写入自动走 WAL 帧复制到云端，读取本地即时返回。`conn.sync()` 做增量帧同步，不需要手工对比元数据。

**执行路径：**

- `sync_databases()` / `sync_hub_databases()`（`database/momo_words.py`）：唯一合法的同步入口，内部只调 `conn.sync()`。旧手工 `_sync_table()` / `_sync_progress_history()` / `_sync_hub_table()` 已于 Phase 3 删除，详见 [`../history/phases/PHASE_3_SYNC_OPTIMIZATION.md`](../history/phases/PHASE_3_SYNC_OPTIMIZATION.md)。
- **前台同步**：用户交互触发，通过 `progress_callback` 回调渲染 CLI 进度条。
- **后台同步**：菜单任务完成、退出收尾、定时 debounce 触发，仅写阶段日志（INFO/WARNING），不干扰交互。

**降级策略：**

- 无 `TURSO_DB_URL` / `TURSO_AUTH_TOKEN` 或 `libsql` 未安装 → 自动退回纯本地 sqlite3 模式。
- `FORCE_CLOUD_MODE=True` 时，若云端不通会提供三选项：立即补配置 / 本次会话临时降级 / 退出并打印修复清单。

## 6. 外部依赖

| 依赖 | 用途 | 封装点 |
| --- | --- | --- |
| 墨墨 OpenAPI | 今日/未来任务、释义/助记/例句/云词本 CRUD | `core/maimemo_api.py`（含 10s/20 次 + 60s/40 次自适应限流、Bearer 认证） |
| Turso (libsql) | 云端备份、多设备同步 | `database/connection.py::_connect_embedded_replica` |
| Gemini | AI 助记生成 | `core/gemini_client.py`（`google-genai` SDK） |
| 小米 Mimo | AI 助记生成（备选） | `core/mimo_client.py`（HTTP + `requests.Session`） |
| 中央 Hub | 多用户元数据、加密凭据、审计日志 | `database/hub_users.py`（Fernet 加密） |

## 7. 同步状态机（sync_status）

`ai_word_notes.sync_status` 三态语义（**只反映"当前用户对该单词的云端释义同步状态"，与内容来源无关**）：

| 值 | 含义 |
| --- | --- |
| `0` | 云端未检出自己的释义 |
| `1` | 云端释义与本地一致 |
| `2` | 云端释义存在，但与本地内容不一致（冲突） |

状态流转细节（初始化规则 / 内存信任快路径 / 冲突处理）见 [`../dev/AUTO_SYNC.md`](../dev/AUTO_SYNC.md) 与 [`DATABASE_DESIGN.md`](DATABASE_DESIGN.md)。

## 8. 关键运行规则

- **AI 提供商切换**：`AI_PROVIDER=mimo|gemini`（默认 `mimo`）。
- **批量大小**：`BATCH_SIZE`（默认 `1`，按实际 AI 并发与上下文限制调整）。
- **AI 并发**：`AI_PIPELINE_WORKERS`（默认 `2`）。
- **时间戳**：统一 ISO 8601 带时区（`get_timestamp_with_tz()` in `database/utils.py`）。
- **用户身份**：`username.strip().lower()` 统一规范化。
- **主菜单**：`1` 今日任务 / `2` 未来计划 / `3` 智能迭代 / `4` 同步并退出。
