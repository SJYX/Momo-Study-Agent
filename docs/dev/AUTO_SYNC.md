# 自动同步机制

## 概述

系统在主流程关键节点自动触发双向同步，保证本地 SQLite 与 Turso 云端尽快收敛。

## 同步触发点

1. 启动后差异检测通过并用户确认“立即合并”
2. 菜单流程完成后触发后台同步线程
3. 用户选择“同步并退出”
4. 程序退出 `finally` 收尾

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
) -> Dict[str, int]:
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
    "status": "ok|skipped|error",  # Hub 目前主要使用 upload/download
    "reason": str
}
```

## 关键约束

1. `db_manager` 同步函数内部不负责 UI 展示，不直接输出进度条
2. 展示层在 `main.py`，通过回调解耦同步逻辑和交互表现
3. 同步失败应记录日志并尽量收尾，避免阻断退出流程
