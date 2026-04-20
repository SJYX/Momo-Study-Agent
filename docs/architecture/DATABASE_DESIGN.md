# 数据库设计

> 这里描述表结构、同步策略和一致性边界。

## 数据层次

- 本地 SQLite：默认工作库，保证离线可用。
- Turso 云端：用户学习数据的同步副本。
- 中央 Hub：用户元数据、会话、统计与审计日志。

## 主要表

### 用户学习库

- `processed_words`：已处理单词去重表。
- `ai_word_notes`：AI 生成的主笔记表。
- `word_progress_history`：熟悉度/复习次数时间线。
- `ai_batches`：批次级 AI 统计。
- `ai_word_iterations`：迭代过程记录。
- `system_config`：少量系统键值配置。

`ai_word_notes` 关键状态字段：

- `sync_status`：同步状态（`0=云端未检出自己的释义`, `1=云端释义与本地一致`, `2=云端释义存在但与本地不一致`）
- `content_origin`：内容来源（例如 `ai_generated`、`community_reused`、`current_db_reused`、`history_reused`）
- `content_source_db`：复用来源的数据库标识（或空值，表示新生成）
- `content_source_scope`：来源范围（例如 `cloud`、`local`、`local_history`）
- `updated_at`：最后更新时间戳（ISO 8601，含时区）

历史数据回填规则：

- 带 `batch_id` 的旧记录，默认回填为 `content_origin = ai_generated`、`content_source_scope = ai_batch`
- 不带任何来源线索的旧记录，回填为 `content_origin = legacy_unknown`、`content_source_scope = legacy`
- `content_source_db` 仅在“复用来源明确”时写入；未知老数据保持空值

### 中央 Hub

- `users`
- `user_api_keys`
- `user_sync_history`
- `user_stats`
- `user_sessions`
- `admin_logs`

## 同步策略

- `sync_databases()` 负责用户学习库的本地/云端双向同步。
- 以主键和时间戳为基础做增量比对。
- `mark_processed()`、`save_ai_word_note()` 和 `save_ai_word_notes_batch()` 会优先写入可用的连接，再回退到本地。
- Hub 同步是独立职责，不和用户学习库混写。

### 带 co_origin 的笔记同步语义

**关键设计原则：** `sync_status` 仅代表**当前用户对该单词的云端同步状态**，与**内容来源**无关。

- `sync_status=0`：云端未检出自己的释义（无论内容来自何处）
- `sync_status=1`：云端释义与本地一致
- `sync_status=2`：云端已存在自己的释义，但内容与本地不一致

**多用户查询命中时的处理：**

当系统查询社区/历史库发现命中（co_origin ≠ ai_generated），_初始化时_ 直接标记为 `sync_status=1`：
- `content_origin = 'community_reused'` → `sync_status=1`（社区释义已在云端，无需当前用户再同步）
- `content_origin = 'current_db_reused'` → `sync_status=1`（个人数据已同步过）
- `content_origin = 'history_reused'` → `sync_status=1`（历史数据已同步）
- `content_origin = 'ai_generated'` → `sync_status=0`（新生成，需要同步）
- `content_origin = 'legacy_unknown'` → `sync_status=0`（旧数据，待审）

**待同步队列过滤：**

`get_unsynced_notes()` 仅返回需要当前用户同步的笔记：
```sql
WHERE sync_status = 0 AND content_origin = 'ai_generated'
```
这样避免了从社区/多库查询命中的笔记被重复加入同步队列。

**状态更新持久化：**

在双库模式（云端+本地缓存）下，`set_note_sync_status()` 确保两库同步：
- 更新主库（云端或本地取决于连接）
- 若主库是云端连接，同时更新本地缓存库
- 确保下次查询不再重复提取

- 待同步队列由 `ai_word_notes.sync_status` 持久化。
- 新增 ai_generated 笔记默认 `sync_status=0`；co_origin 笔记默认 `sync_status=1`。
- 同步成功后可调用 `mark_note_synced(voc_id)` 将记录置为 `sync_status=1`。
- 若云端已存在释义但内容与本地不一致，可将记录标记为 `sync_status=2` 以便后续冲突排查。
- 查重命中的结果应写入 `content_origin` / `content_source_db` / `content_source_scope`，不要复用 `sync_status` 表达来源。
- 同步执行前可通过 `get_unsynced_notes()` 按时间顺序提取待同步记录（仅 ai_generated 笔记）。

## 本地并发设置

- 本地 SQLite 连接默认启用 `PRAGMA journal_mode=WAL`。
- 本地 SQLite 连接默认启用 `PRAGMA synchronous=NORMAL`。
- 本地连接超时设置为 `20.0s`，降低写入竞争导致的锁超时风险。

## 冲突处理

- 以“较新记录优先”为默认原则。
- 已处理单词优先去重，不重复触发 AI。
- 进度历史按 `created_at` 保留时间线。

## 相关文档

- [DATA_FLOW.md](DATA_FLOW.md)
- [../dev/AUTO_SYNC.md](../dev/AUTO_SYNC.md)
- [../dev/CONTRIBUTING.md](../dev/CONTRIBUTING.md)
