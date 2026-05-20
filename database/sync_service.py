from __future__ import annotations
"""
database/sync_service.py: Embedded Replica 帧级同步管线（主库 + Hub 库）。

边界：
- 仅处理 conn.sync() 调用、进度回调、错误归类和 skip 状态。
- 写队列/连接池在 connection.py；表 schema 初始化在 schema.py。
- 日志 module 名保留 "database.momo_words"。
"""

import os
import time
from typing import Any, Callable, Dict, Optional

from . import connection
from .backends import get_active_backend
from .schema import _init_hub_schema
from .utils import _debug_log


def _emit_sync_progress(progress_callback: Optional[Callable[[Dict[str, Any]], None]], stage: str, current: int, total: int, message: str, **extra) -> None:
    if not progress_callback:
        return
    payload = {"stage": stage, "current": current, "total": total, "message": message}
    if extra:
        payload.update(extra)
    try:
        progress_callback(payload)
    except Exception:
        pass


def _is_cloud_connection_unavailable_error(error: Exception) -> bool:
    msg = str(error or "").lower()
    return (
        "强制云端模式已启用" in str(error or "")
        or "cannot connect to the cloud" in msg
        or "unable to connect" in msg
        or "failed to connect" in msg
        or ("cloud" in msg and "unavailable" in msg)
    )


def _run_libsql_sync_pipeline(
    *,
    creds_ok: bool,
    creds_skip_reason: str,
    conn_factory: Callable[[], Any],
    conn_op_lock: Any,
    dry_run: bool,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    messages: Dict[str, str],
    skip_reason_local_only: str,
    pre_setup: Optional[Callable[[], None]] = None,
) -> Dict[str, Any]:
    # Shared scaffolding for sync_databases / sync_hub_databases. See messages keys in callers.
    stats: Dict[str, Any] = {"upload": 0, "download": 0, "status": "ok", "reason": ""}

    if not creds_ok:
        stats["status"] = "skipped"
        stats["reason"] = creds_skip_reason
        _emit_sync_progress(progress_callback, "skipped", 0, 0, messages["skip_creds_msg"], status="skipped", reason=creds_skip_reason)
        return stats

    sync_start = time.time()
    try:
        _emit_sync_progress(progress_callback, "connect", 1, 2, messages["connect"])

        if pre_setup is not None:
            try:
                pre_setup()
            except Exception as e:
                _debug_log(f"{messages['error_log_prefix']} 预初始化警告（非致命）: {e}", module="database.momo_words")

        try:
            conn = conn_factory()
        except Exception as conn_error:
            if _is_cloud_connection_unavailable_error(conn_error):
                stats["status"] = "skipped"
                stats["reason"] = "cloud-unavailable"
                _emit_sync_progress(progress_callback, "skipped", 0, 0, f"{messages['cloud_unavail_skip_prefix']}: {conn_error}", status="skipped", reason=stats["reason"])
                return stats
            raise

        if not (hasattr(conn, "sync") or hasattr(conn, "pull")):
            stats["status"] = "skipped"
            stats["reason"] = skip_reason_local_only
            _emit_sync_progress(progress_callback, "done", 1, 2, messages["local_only"], status="skipped")
            return stats

        _emit_sync_progress(progress_callback, "sync", 1, 2, messages["sync_doing"])

        if not dry_run:
            import threading as _threading
            _sync_timeout = float(os.getenv("MOMO_SYNC_TIMEOUT_S", "3"))
            sync_done_evt = _threading.Event()
            sync_result_box = [None]
            sync_err_box = [None]

            def _do_sync():
                try:
                    # 锁必须由本线程持有：外层只持有锁等 sync_done，
                    # 超时后释放锁会让 sync 与其他线程并发碰 libsql C 层（access violation）。
                    if conn_op_lock is not None:
                        with conn_op_lock:
                            get_active_backend().do_sync_on(conn)
                    else:
                        get_active_backend().do_sync_on(conn)
                    sync_result_box[0] = True
                except Exception as e:
                    sync_err_box[0] = e
                finally:
                    sync_done_evt.set()

            t = _threading.Thread(target=_do_sync, daemon=True, name="SvcSyncOp")
            t.start()
            # 软超时：超时后 daemon 路径继续；子线程仍持锁完成 sync()，
            # 其他读线程会安全等待——而不是与 sync() 并发崩溃。
            sync_done_evt.wait(timeout=_sync_timeout)

            if not sync_done_evt.is_set():
                _debug_log(
                    f"sync_service conn.sync() 超时 ({_sync_timeout}s)，sync 线程仍持锁在后台完成",
                    level="WARNING",
                    module="database.sync_service",
                )
                t.join(timeout=30.0)

            if sync_err_box[0] is not None:
                raise sync_err_box[0]

            sync_result = sync_result_box[0]
            stats["frames_synced"] = getattr(sync_result, "frames_synced", 0) if sync_result else 0

        _emit_sync_progress(progress_callback, "done", 2, 2, messages["done"], upload=0, download=0)
        stats["duration_ms"] = int((time.time() - sync_start) * 1000)
        stats["status"] = "ok"
        return stats
    except Exception as e:
        _debug_log(f"{messages['error_log_prefix']}: {e}", level="WARNING", module="database.momo_words")
        stats["status"] = "error"
        stats["reason"] = str(e)
        _emit_sync_progress(progress_callback, "error", 0, 0, f"{messages['error_progress_prefix']}: {e}", status="error", reason=str(e))
        return stats


def sync_databases(
    db_path: Optional[str] = None,
    dry_run: bool = False,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    from config import DB_PATH

    path = db_path or DB_PATH
    creds_ok = bool(os.getenv("TURSO_DB_URL") and os.getenv("TURSO_AUTH_TOKEN") and (connection.HAS_LIBSQL or connection.HAS_PYTURSO))
    if not (os.getenv("TURSO_DB_URL") and os.getenv("TURSO_AUTH_TOKEN")):
        creds_skip_reason = "missing-cloud-credentials"
    else:
        creds_skip_reason = "libsql-unavailable"

    def _factory():
        if connection._is_main_db_path(path):
            return connection._get_main_write_conn_singleton(do_sync=False)
        return connection._get_conn(path, do_sync=False)

    return _run_libsql_sync_pipeline(
        creds_ok=creds_ok,
        creds_skip_reason=creds_skip_reason,
        conn_factory=_factory,
        conn_op_lock=connection._main_write_conn_op_lock,
        dry_run=dry_run,
        progress_callback=progress_callback,
        messages={
            "skip_creds_msg": f"跳过同步: {creds_skip_reason}",
            "connect": "连接 Embedded Replica 数据库",
            "cloud_unavail_skip_prefix": "跳过同步",
            "sync_doing": "执行帧级增量同步...",
            "local_only": "本地模式，无需同步",
            "done": "同步完成",
            "error_log_prefix": "数据库同步失败",
            "error_progress_prefix": "同步失败",
        },
        skip_reason_local_only="local-only-connection",
    )


def sync_hub_databases(
    dry_run: bool = False,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    hub_url = os.getenv("TURSO_HUB_DB_URL")
    hub_token = os.getenv("TURSO_HUB_AUTH_TOKEN")
    creds_ok = bool(hub_url and hub_token and (connection.HAS_LIBSQL or connection.HAS_PYTURSO))
    creds_skip_reason = (
        "missing-hub-cloud-credentials"
        if not (hub_url and hub_token)
        else "libsql-unavailable"
    )

    def _pre_setup():
        local_hub_conn = connection._get_hub_local_conn()
        try:
            _init_hub_schema(local_hub_conn)
        finally:
            try:
                local_hub_conn.close()
            except Exception:  # noqa: BLE001 - close 不应阻塞同步主流程
                pass

    return _run_libsql_sync_pipeline(
        creds_ok=creds_ok,
        creds_skip_reason=creds_skip_reason,
        conn_factory=connection._get_hub_conn,
        conn_op_lock=connection._hub_write_conn_op_lock,
        dry_run=dry_run,
        progress_callback=progress_callback,
        messages={
            "skip_creds_msg": "跳过 Hub 同步: 云端凭据或 libsql 不可用",
            "connect": "连接 Hub Embedded Replica 数据库",
            "cloud_unavail_skip_prefix": "跳过 Hub 同步",
            "sync_doing": "执行 Hub 帧级增量同步...",
            "local_only": "Hub 本地模式，无需同步",
            "done": "Hub 同步完成",
            "error_log_prefix": "Hub 同步失败",
            "error_progress_prefix": "Hub 同步失败",
        },
        skip_reason_local_only="local-only-hub-connection",
        pre_setup=_pre_setup,
    )


__all__ = [
    "sync_databases",
    "sync_hub_databases",
]
