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

## 冲突处理

- 以“较新记录优先”为默认原则。
- 已处理单词优先去重，不重复触发 AI。
- 进度历史按 `created_at` 保留时间线。

## 相关文档

- [DATA_FLOW.md](DATA_FLOW.md)
- [../dev/AUTO_SYNC.md](../dev/AUTO_SYNC.md)
- [../dev/CONTRIBUTING.md](../dev/CONTRIBUTING.md)