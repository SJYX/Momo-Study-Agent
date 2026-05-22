"""
database/execution_engine.py: 专职处理并发队列、写操作防冲突以及定时同步。
从 connection.py 解耦出来的执行引擎层。
"""
import os
import queue
import threading
import time
from typing import Any, Dict, List, Tuple, Optional

import config as _config
# 稍后我们需要依赖底层的连接管理功能，所以要向 connection.py 拿连接单例。
# 注意：不再从 connection 导入 DB_PATH（Phase 6.4 起它不在 connection 模块级了）；
# 直接读 `_config.DB_PATH` 让 switch_user 立即生效。HUB_DB_PATH 仍是静态可缓存的。
from database.connection import (
    _get_dedicated_write_conn,
    _close_main_write_conn_singleton,
    _close_hub_write_conn_singleton,
    _is_main_db_path,
    _get_local_conn,
    HUB_DB_PATH,
)
from core.logger import get_logger
from database.backends import get_active_backend

# 内部状态
_write_queue = queue.Queue(maxsize=10000)
_writer_daemon_thread: Optional[threading.Thread] = None
_writer_daemon_stop_event = threading.Event()
_writer_daemon_lock = threading.Lock()

# Phase 2: Sync daemon replaced by per-profile ProfileSyncCoordinator.
# Writes trigger coordinator.mark_dirty() → 5s debounce timer → push/pull/checkpoint.
# No global polling, no cross-profile state.

# DB 级别的 Embedded Replica 同步状态（供前端展示）
_db_syncing = False
_db_sync_progress: Dict[str, Any] = {}  # {"started_at": float, "phase": str}

_write_queue_stats = {
    "total_queued": 0,
    "total_written": 0,
    "total_errors": 0,
    "last_batch_size": 0,
}

# 慢阈值（毫秒）：批写超过此值会被打成 WARNING（Phase 4.5 P95<100ms 对齐）
_SLOW_BATCH_WRITE_MS = 100

def set_db_syncing(phase: str = "") -> None:
    """标记 DB 正在同步（嵌入式副本的 conn.sync() 进行中）。"""
    global _db_syncing, _db_sync_progress
    _db_syncing = True
    _db_sync_progress = {"started_at": time.time(), "phase": phase}


def clear_db_syncing() -> None:
    """清除 DB 同步标记。"""
    global _db_syncing, _db_sync_progress
    _db_syncing = False
    _db_sync_progress = {}


def get_db_sync_status() -> Dict[str, Any]:
    """返回 DB 同步状态，供 health endpoint 使用。"""
    return {
        "syncing": _db_syncing,
        **(_db_sync_progress if _db_syncing else {}),
    }


def _debug_log(msg: str, level: str = "DEBUG") -> None:
    try:
        logger = get_logger()
        func = getattr(logger, level.lower(), None)
        if callable(func):
            func(msg, module="database.execution_engine")
        else:
            logger.debug(msg)
    except Exception:
        pass

def _execute_batch_writes_unlocked(write_conn: Any, batch: List[Dict[str, Any]]) -> None:
    cur = write_conn.cursor()
    t0 = time.time()
    try:
        # 【关键修复】使用具名游标执行，绝不能用 write_conn.execute
        cur.execute("BEGIN IMMEDIATE")
        t1 = time.time()
        for item in batch:
            op_type = item.get("op_type", "insert")
            if op_type == "insert_or_replace":
                sql = item.get("sql")
                args = item.get("args", ())
                cur.execute(sql, args)
            elif op_type == "executemany":
                sql = item.get("sql")
                args_list = item.get("args_list", [])
                if args_list:
                    cur.executemany(sql, args_list)
        t2 = time.time()
        write_conn.commit()
        t3 = time.time()

        # 仅在慢查询时详细记录分段耗时
        duration_ms = int((t3 - t0) * 1000)
        if duration_ms >= 500:
            _debug_log(
                f"[Profiling] batch_write detail | total={duration_ms}ms | "
                f"begin={int((t1-t0)*1000)}ms | exec={int((t2-t1)*1000)}ms | commit={int((t3-t2)*1000)}ms",
                level="INFO"
            )
    except Exception:
        # 如果发生任何异常，强行回滚，防止事务卡死
        try:
            write_conn.rollback()
        except Exception:
            pass
        raise
    finally:
        cur.close()


def _execute_batch_writes(write_conn: Any, batch: List[Dict[str, Any]]) -> None:
    if not batch:
        return

    max_retries = 3
    retry_count = 0
    last_error = None
    started_at = time.time()

    while retry_count < max_retries:
        try:
            with get_active_backend().op_lock_for(write_conn):
                _execute_batch_writes_unlocked(write_conn, batch)
            duration_ms = int((time.time() - started_at) * 1000)
            is_slow = duration_ms >= _SLOW_BATCH_WRITE_MS
            try:
                logger = get_logger()
                msg = f"batch_write done | size={len(batch)} | duration_ms={duration_ms} | retries={retry_count}"
                kwargs = dict(
                    module="database.execution_engine",
                    batch_size=len(batch),
                    duration_ms=duration_ms,
                    retries=retry_count,
                    is_slow=is_slow,
                )
                if is_slow:
                    logger.warning(msg + " | slow=true", **kwargs)
                else:
                    logger.info(msg, **kwargs)
            except Exception:
                pass
            # PLAYBOOK B5：写入指标层，给 B3 闲时引擎与 /api/ops/metrics 用
            try:
                from core.metrics import get_metrics_collector
                from core.active_profile_registry import get_active
                get_metrics_collector().record(
                    get_active() or "_global",
                    "db.batch_write.duration_ms",
                    float(duration_ms),
                )
            except Exception:
                pass
            return
        except Exception as e:
            # pyturso 原生 MVCC 不会产生 WalConflict，但并发下仍可能出现 "database is locked" 等瞬时错误。
            # 保留通用重试：对可重试的瞬时错误做指数退避重试。
            error_msg = str(e).lower()
            is_transient = (
                "database is locked" in error_msg
                or "wal" in error_msg
                or "busy" in error_msg
            )
            if is_transient and retry_count < max_retries - 1:
                retry_count += 1
                wait_time = 0.1 * (2 ** (retry_count - 1))
                _debug_log(
                    f"批量写入瞬时错误，等待 {wait_time*1000:.0f}ms 后重试 ({retry_count}/{max_retries}): {e}",
                    level="WARNING",
                )
                time.sleep(wait_time)
                try:
                    write_conn.rollback()
                except Exception:
                    pass
                last_error = e
                continue

            try:
                write_conn.rollback()
            except Exception:
                pass
            raise

    if last_error:
        raise last_error

def _flush_grouped_batch(pending_batch: List[Dict[str, Any]]) -> None:
    """按 db_path 分组刷写，确保不同 profile 的写入不会串乱。
    写入成功后通知 per-profile coordinator 启动 debounce 定时器。
    """
    from collections import defaultdict
    from database.sync_coordinator import mark_db_written

    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in pending_batch:
        groups[item.get("db_path", _config.DB_PATH)].append(item)

    for db_path, items in groups.items():
        try:
            write_conn = _get_dedicated_write_conn(db_path)
            _execute_batch_writes(write_conn, items)
            _write_queue_stats["total_written"] += len(items)
            _write_queue_stats["last_batch_size"] = len(items)
            mark_db_written(db_path)
        except Exception as e:
            _write_queue_stats["total_errors"] += 1
            err_msg = str(e).lower()
            is_broken_conn = any(k in err_msg for k in [
                "invalid state", "txn", "poison", "wal", "stream not found", "hrana"
            ])
            if is_broken_conn:
                _debug_log(f"检测到 Turso 云端连接休眠或底层状态失效（db_path={db_path[:30]}...），正在静默重建单例并重试...", level="INFO")
                _close_main_write_conn_singleton()
                time.sleep(0.5)
                try:
                    write_conn = _get_dedicated_write_conn(db_path)
                    _execute_batch_writes(write_conn, items)
                    _write_queue_stats["total_written"] += len(items)
                    mark_db_written(db_path)
                except Exception as retry_e:
                    _debug_log(f"后台写线程重试失败（db_path={db_path[:30]}...）: {retry_e}", level="ERROR")
            else:
                _debug_log(f"后台写线程批量操作出错（db_path={db_path[:30]}...）: {e}", level="ERROR")


def _writer_daemon() -> None:
    batch_threshold = 50
    timeout_seconds = 1.0

    pending_batch: List[Dict[str, Any]] = []
    last_commit_time = time.time()

    try:
        _debug_log("后台写线程启动", level="INFO")

        while True:
            if _writer_daemon_stop_event.is_set() and _write_queue.empty() and not pending_batch:
                break

            try:
                try:
                    item = _write_queue.get(timeout=0.1)
                    pending_batch.append(item)
                    _write_queue_stats["total_queued"] += 1
                except queue.Empty:
                    pass

                now = time.time()
                should_commit = (
                    len(pending_batch) >= batch_threshold
                    or (pending_batch and (now - last_commit_time) >= timeout_seconds)
                    or (_writer_daemon_stop_event.is_set() and pending_batch)
                )

                if should_commit and pending_batch:
                    _flush_grouped_batch(pending_batch)
                    pending_batch = []
                    last_commit_time = now
            except Exception as e:
                _write_queue_stats["total_errors"] += 1
                _debug_log(f"后台写线程外层捕获出错: {e}", level="ERROR")
                time.sleep(0.1)

        if pending_batch:
            try:
                _flush_grouped_batch(pending_batch)
            except Exception as e:
                _write_queue_stats["total_errors"] += 1
                _debug_log(f"后台写线程关机批量操作出错: {e}", level="ERROR")

    except BaseException as e:
        _debug_log(f"后台写线程崩溃: {e}", level="CRITICAL")
    finally:
        _debug_log("后台写线程停止", level="INFO")

_SYNC_TIMEOUT_S = float(os.getenv("MOMO_SYNC_TIMEOUT_S", "3"))

# Phase 2: Sync daemon removed. DB sync is now handled by per-profile
# ProfileSyncCoordinator (database/sync_coordinator.py).
# Each coordinator uses a threading.Timer for 5s debounce after writes.
# No global polling loop, no cross-profile state.

def _start_writer_daemon() -> None:
    global _writer_daemon_thread
    with _writer_daemon_lock:
        if _writer_daemon_thread is None or not _writer_daemon_thread.is_alive():
            _writer_daemon_stop_event.clear()
            _writer_daemon_thread = threading.Thread(target=_writer_daemon, daemon=True, name="MomoDBWriter")
            _writer_daemon_thread.start()
            _debug_log("后台写守护线程已启动", level="INFO")

def _stop_writer_daemon(timeout_seconds: float = 2.0) -> None:
    global _writer_daemon_thread
    _writer_daemon_stop_event.set()
    if _writer_daemon_thread and _writer_daemon_thread.is_alive():
        _writer_daemon_thread.join(timeout=timeout_seconds)

def _queue_write_operation(sql: str, args: Tuple = (), op_type: str = "insert_or_replace", db_path: Optional[str] = None) -> bool:
    """入队单条写操作。db_path 在入队时捕获，防止多 profile 并发时全局 DB_PATH 被覆盖导致交叉写污染。"""
    _start_writer_daemon()
    item = {"op_type": op_type, "sql": sql, "args": args, "db_path": db_path or _config.DB_PATH}
    try:
        _write_queue.put(item, timeout=2.0)
        return True
    except queue.Full:
        _debug_log(f"写队列满，丢弃操作: {sql[:100]}", level="WARNING")
        return False

def _queue_batch_write_operation(sql: str, args_list: List[Tuple], db_path: Optional[str] = None) -> bool:
    if not args_list:
        return True
    _start_writer_daemon()
    item = {"op_type": "executemany", "sql": sql, "args_list": args_list, "db_path": db_path or _config.DB_PATH}
    try:
        _write_queue.put(item, timeout=2.0)
        return True
    except queue.Full:
        _debug_log(f"写队列满，丢弃批量操作: {sql[:100]} | size={len(args_list)}", level="WARNING")
        return False

def init_concurrent_system() -> None:
    _start_writer_daemon()
    # Phase 2: sync daemon removed — per-profile ProfileSyncCoordinator handles DB sync
    _debug_log("并发系统初始化完成", level="INFO")

def cleanup_concurrent_system() -> None:
    _stop_writer_daemon(timeout_seconds=5.0)
    # Phase 2: coordinators are cleaned up per-profile via UserContext._cleanup_context
    _close_main_write_conn_singleton()
    _close_hub_write_conn_singleton()
    _debug_log("并发系统清理完成", level="INFO")

def _release_db_file_handles_for_recovery(db_path: str) -> None:
    import os
    abs_path = os.path.abspath(db_path or _config.DB_PATH)
    # Phase 2: no global sync daemon to stop
    try:
        _stop_writer_daemon(timeout_seconds=1.5)
    except Exception:
        pass

    try:
        if abs_path == os.path.abspath(_config.DB_PATH):
            _close_main_write_conn_singleton()
        if abs_path == os.path.abspath(HUB_DB_PATH):
            _close_hub_write_conn_singleton()
    except Exception as singleton_error:
        _debug_log(f"恢复前释放写连接单例失败: {singleton_error}", level="WARNING")

def _mark_main_db_needs_sync(db_path: Optional[str] = None, conn: Any = None) -> None:
    """Notify the per-profile coordinator that a write occurred.

    Used by non-queued write paths (direct SQL via session.py decorators).
    """
    from database.sync_coordinator import mark_db_written

    if conn is not None:
        if get_active_backend().should_close(conn):
            return
    elif not _is_main_db_path(db_path):
        return

    path = db_path or _config.DB_PATH
    mark_db_written(path)

def _execute_write_sql_sync(sql: str, params: tuple = (), db_path: Optional[str] = None, conn: Any = None) -> None:
    owned = conn is None
    target_conn = conn or _get_local_conn(db_path or _config.DB_PATH)
    try:
        cur = target_conn.cursor()
        try:
            cur.execute(sql, params)
        finally:
            cur.close()
        target_conn.commit()
        _mark_main_db_needs_sync(db_path=db_path, conn=target_conn)
    finally:
        if owned:
            try:
                target_conn.close()
            except Exception:
                pass

def _execute_batch_write_sql_sync(
    sql: str,
    args_list: List[Tuple],
    db_path: Optional[str] = None,
    conn: Any = None,
) -> None:
    if not args_list:
        return

    owned = conn is None
    target_conn = conn or _get_local_conn(db_path or _config.DB_PATH)
    try:
        cur = target_conn.cursor()
        try:
            cur.executemany(sql, args_list)
        finally:
            cur.close()
        target_conn.commit()
        _mark_main_db_needs_sync(db_path=db_path, conn=target_conn)
    finally:
        if owned:
            try:
                target_conn.close()
            except Exception:
                pass

def get_write_queue_stats() -> Dict[str, int]:
    return dict(_write_queue_stats)
