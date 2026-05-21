# 数据库操作原子性与性能优化审查指南 (2026-05-12)

本文档旨在为后续的代码审查（AI Review）提供详尽的背景、修改清单及架构权衡说明。本次迭代核心聚焦于**高并发场景下的数据一致性保障**、**减少 SQLite N+1 读写开销**以及**外部服务抖动时的平滑降级**。

---

## 1. 核心问题与重构动因

在多代理并行调度及高频学习流处理中，旧有架构暴露了以下痛点：
1. **部分失败与非原子更新**：单词的 AI 迭代记录插入（`INSERT`）与笔记状态更新（`UPDATE`）分两步执行，若中途发生异常或进程中断，易出现记录和状态脱节。
2. **N+1 数据库访问瓶颈**：在状态重置与去重流程中，对多个 `voc_id` 循环调用单条查询接口获取笔记详情，显著增加了锁争用与微秒级 I/O 延迟。
3. **只读操作中的冗余事务开销**：大量纯数据拉取接口在结束游标后，不必要地调用了 `conn.commit()`，在高频读场景下加剧了 SQLite 并发锁冲突概率。
4. **云端抖动导致页面加载受阻**：获取今日学习列表时缺乏防超时机制，若远程服务响应过慢将直接导致前端白屏。

---

## 2. 变更详情清单

### 2.1 数据库与底层存储层 (`database/`)
- **`database/momo_words.py` & `database/notes_repo.py`**
  - **[新增]** `atomic_save_iteration_and_update_note`：引入基于 SQLite `BEGIN IMMEDIATE` 显式事务控制的原子化方法，利用单例连接操作锁 (`conn_lock`) 将迭代日志写入与笔记最新状态更新合并为单一不可分割的事务单元。
  - **[新增]** `get_word_notes_in_batch`：实现基于 `IN (?, ?, ...)` 占位符的批量查询函数，将原本 O(N) 次 SQL 交互收敛为单次拉取并建立哈希映射表，极大地优化了批量重载性能。
  - **[优化]** `save_ai_word_notes_batch`：在批量操作入口生成统一的带时区时间戳 (`timestamp`)，减少循环内部重复调用时间系统 API 的额外微秒级损耗。

- **`database/schema.py`**
  - **[新增]** `_hub_init_state_is_fresh` 短路判定：通过校验数据库指纹与内存级最后成功校验时间戳，避免重复发起 DDL 表存在性检测请求。
  - **[优化]** `init_users_hub_tables`：引入多表全量预检机制，若所有系统关键表均已就绪则即刻跳过后续分表建表逻辑。

- **`database/session.py`**
  - **[移除]** 清理了 `DBSession.fetchall` 与 `fetchone` 等纯读操作退出路径上的 `self.conn.commit()`，消除了多余的隐式读写锁升级与日志落盘动作。

### 2.2 核心业务逻辑层 (`core/`)
- **`core/iteration_manager.py`**
  - 改造 `_update_it_state`，全面切入 `atomic_save_iteration_and_update_note` 路径，保障迭代记录堆栈与笔记级别字段的强一致性。
- **`core/study_workflow.py`**
  - 重构 `recover_processed_status` 方法，利用 `get_word_notes_in_batch` 一次性获取当前批次全部相关笔记状态，显著加速进度同步与重复词过滤效率。
- **`core/weak_word_filter.py`**
  - 为 `_get_user_stats` 增加 60 秒生命周期 (TTL) 的内存级结果缓存，避免频繁切页或弹窗触发高频聚合统计对主 DB 造成读压。

### 2.3 Web API 路由层 (`web/backend/routers/`)
- **`web/backend/routers/study.py`**
  - 在 `get_today` 今日数据拉取逻辑中加入 `asyncio.wait_for` 超时熔断机制（默认 8 秒）；当远端 API 响应超时，自动读取本地磁盘上的历史生数据 (`_load_today_items_raw`) 作为 fallback，确保前端用户界面的基础连续性。
- **`web/backend/routers/words.py`**
  - 优化连接锁获取策略，采用非阻塞等待超时模式 `conn_lock.acquire(timeout=2.0)`，同时去除纯数据读取完毕后的无关 `commit()`。

---

## 3. 审查与验证重点提示

审查本变更时，请重点关注：
1. **死锁与超时防范**：新增的事务包含 `BEGIN IMMEDIATE`，已通过最外层及内部机制包装了 `try...except...finally` 回滚与资源释放保障。
2. **后向兼容性**：在 `notes_repo.py` 中，时间戳与事务层传递参数均支持 `Optional` 并留有合理的默认兜底生成机制，不会影响外部旧有直接调用场景。
3. **缓存击穿与过期**：`WeakWordFilter` 中的用户状态缓存生命周期较短（60s），既满足了瞬时防抖，也确保了长期数据的相对新鲜度。
