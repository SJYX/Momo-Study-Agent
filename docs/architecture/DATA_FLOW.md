# 数据流

> 这里聚焦“数据从哪里来、经过哪些步骤、写到哪里去”。

## 今日任务流程

1. [main.py](../../main.py) 调用 `MaiMemoAPI.get_today_items()` 拉取今日词汇。
2. `db_manager.get_processed_ids_in_batch()` 过滤已处理单词。
3. `db_manager.find_words_in_community_batch()` 尝试复用社区缓存。
4. AI 客户端批量生成助记。
5. `save_ai_word_note()` 与 `mark_processed()` 写入本地/云端数据。
6. `sync_interpretation()` 与 `create_note()` 将结果写回墨墨。
7. `_trigger_post_run_sync()` 触发后台同步。

## 未来计划流程

1. 主流程先拉取未来 7 天计划。
2. 用户可指定自定义天数。
3. 其余步骤与今日任务一致，只是数据来源不同。

## 智能迭代流程

1. `WeakWordFilter` 选择薄弱词。
2. `IterationManager` 按 `it_level` 分支：
   - `it_level == 0`：选优同步。
   - `it_level > 0`：根据熟悉度变化决定是否重炼。
3. 结果会写入 `ai_word_iterations` 和 `ai_word_notes`。
4. 重炼结果会追加到 `MomoAgent: 薄弱词攻坚` 云词本。

## 同步边界

- `sync_databases()` 同步用户数据表：`processed_words`、`word_progress_history`、`ai_batches`、`system_config`，以及可用的 AI 笔记/迭代数据。
- `sync_hub_databases()` 同步 Hub 层表：`users`、`user_sessions`、`user_stats`、`admin_logs` 等。
- `FORCE_CLOUD_MODE` 只影响云端优先级，不改变本地缓存存在。

## 相关代码

- [main.py](../../main.py)
- [core/db_manager.py](../../core/db_manager.py)
- [core/iteration_manager.py](../../core/iteration_manager.py)