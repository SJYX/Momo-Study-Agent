# 自动同步机制

## 概述

系统在主流程关键节点自动触发双向同步，保证本地 SQLite 与 Turso 云端尽快收敛。

## 同步触发点

1. 启动后差异检测通过并用户确认“立即合并”
2. 菜单流程完成后触发后台同步线程
3. 用户选择“同步并退出”
4. 程序退出 `finally` 收尾

## 断点续传

- 启动时的遗留待同步队列从本地数据库读取，避免云端模式下的额外握手和兼容性问题。
- 断点续传依赖本地 `ai_word_notes.sync_status`，因此需要先完成本地 schema 初始化，再恢复待同步队列。
- 如果日志里出现 `获取未同步笔记失败`，优先检查本地库 schema 与 `sync_status` 列是否存在。

### 退出收尾策略

- 退出阶段的自动同步采用守护线程执行，不会阻塞程序最终退出。
- 主线程仅在 `EXIT_SYNC_TIMEOUT_S` 时间窗内等待结果；超时后记录告警并直接收尾。
- 该策略用于避免云端/Hub 网络抖动拖住终端退出。
- 若检测到已有后台同步线程正在执行，退出阶段会优先复用该线程并等待其完成，避免重复发起双库同步造成拥塞。
- 退出阶段会输出聚合状态（`success|partial|failed`）和任务摘要，避免“超时/失败仍显示已同步”的误导提示。
- 退出等待时长支持按本会话最近同步耗时动态放大：以 `EXIT_SYNC_TIMEOUT_S` 为基础值，结合近几次“用户数据库+中央 Hub”耗时估算并在上限内调整。

## 启动加速策略

- 启动一致性检查采用“限时等待 + 后台补偿”机制。
- 主线程仅等待 `STARTUP_SYNC_CHECK_TIMEOUT_S`（默认 `2.5s`）。
- 若超时：先进入主菜单，后台完成 dry-run 一致性检查并写阶段日志。
- 后台检查若发现差异，会记录告警并提示用户在菜单执行同步。

## 同步函数签名

```python
def sync_databases(
    db_path: str = None,
    dry_run: bool = False,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, int]:
    ...

def sync_hub_databases(
    dry_run: bool = False,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    ...
```

回调 payload 至少包含：

- `stage`: `connect|table|table-done|finalize|error|skipped|table-error`
- `current`
- `total`
- `message`

## 前台与后台显示策略

### 前台同步（用户交互路径）

- 由 `main.py` 的 `_run_sync_with_progress()` 驱动
- 使用 `progress_callback` 更新 CLI 进度条
- 仍保留日志落盘

```python
def _run_sync_with_progress(self, label: str, sync_func, dry_run: bool = False) -> dict:
    def _on_progress(payload: dict):
        self._render_sync_progress(label, payload)

    return sync_func(dry_run=False, progress_callback=_on_progress)
```

### 后台同步（自动触发路径）

- 由 `_run_sync_with_stage_logs()` 驱动
- 只记阶段日志（`logger.info/warning`），不输出进度条
- 适用于后台线程与自动收尾，避免刷屏

```python
def _run_sync_with_stage_logs(self, label: str, sync_func) -> dict:
    def _on_progress(payload: dict):
        if payload.get("stage") in {"error", "table-error"}:
            self.logger.warning(f"[{label}] {payload.get('message', '')}", module="main")
        else:
            self.logger.info(f"[{label}] {payload.get('message', '')}", module="main")

    return sync_func(dry_run=False, progress_callback=_on_progress)
```

## 同步范围

### 用户库（`sync_databases`）

- `ai_word_notes`
- `processed_words`
- `word_progress_history`
- `ai_batches`
- `system_config`

### 队列状态持久化（`ai_word_notes.sync_status`）

**关键设计：** `sync_status` 仅表示**当前用户对该单词的云端同步状态**，与**内容来源**完全独立。

- `sync_status = 0`：云端未检出自己的释义（默认值，仍可继续尝试同步）
- `sync_status = 1`：云端释义与本地一致
- `sync_status = 2`：云端释义存在，但与本地内容不一致


**笔记初始化时的状态设置规则：**

- `content_origin = 'ai_generated'` → 默认 `sync_status = 0`（新生成，需要同步）
- `content_origin = 'community_reused'` → 默认 `sync_status = 1`（社区释义已在云端）
- `content_origin = 'current_db_reused'` → 默认 `sync_status = 1`（个人数据已同步）
- `content_origin = 'history_reused'` → 默认 `sync_status = 1`（历史数据已同步）
- `content_origin = 'legacy_unknown'` → 默认 `sync_status = 0`（旧数据，待审）


**断点续传和队列过滤：**

- `get_unsynced_notes()` **只返回** `sync_status = 0 AND content_origin = 'ai_generated'` 的笔记
- 这确保了来自社区/多库查询命中的笔记不会被重复加入待同步队列（它们已标记为 sync_status=1）
- co_origin 笔记实际上已经存在于云端，无需当前用户再同步


- 入队顺序约束：`main.py` 在生成结果处理中必须先调用批量落库，再将任务加入收尾同步队列；禁止“先入队后落库”，避免后台线程先消费导致误报“未检索到记录”。

**状态更新和持久化：**

- 可通过 `mark_note_synced(voc_id)` 在单词同步成功后标记为已同步
- 可通过 `set_note_sync_status(voc_id, 2)` 标记冲突态，便于后续人工核对或定向处理
- 在双库模式（云端+本地缓存）下，状态更新自动同步到两库，避免下次查询时重复提取

**内容来源信息：**

- 查重命中时应更新 `content_origin` / `content_source_db` / `content_source_scope`，它们只描述内容复用来源，不代表当前用户云端同步状态
- 老数据会被保守回填：有 `batch_id` 的记录默认视为 `ai_generated`，没有来源线索的记录标记为 `legacy_unknown`

**异常状态处理：**

- 当墨墨返回 `interpretation_create_limitation` 且未核验到远端已存在释义时，任务保持 `sync_status = 0`，避免误标成功
- 当核验到远端已存在释义但文本与本地不一致时，记录会进入 `sync_status = 2`

该机制用于在网络抖动、重试或异常中断时保留"待同步"队列，避免漏传。

该机制用于在网络抖动、重试或异常中断时保留“待同步”队列，避免漏传。

## 本地并发写入配置

- 本地 SQLite 连接启用 `WAL` 模式与 `synchronous=NORMAL`
- 本地连接超时调整为 `20.0s`（降低高并发写入场景下的锁等待失败）

### Hub 库（`sync_hub_databases`）

- `users`
- `user_stats`
- `user_auth`
- `user_sessions`
- `user_sync_history`
- `admin_logs`
- `user_credentials`

## 返回值约定

两类函数均返回：

```python
{
    "upload": int,
    "download": int,
    "status": "ok|partial|skipped|error",
    "reason": str
}
```

## 关键约束

1. `db_manager` 同步函数内部不负责 UI 展示，不直接输出进度条
2. 展示层在 `main.py`，通过回调解耦同步逻辑和交互表现
3. 同步失败应记录日志并尽量收尾，避免阻断退出流程
