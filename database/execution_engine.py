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
    _get_main_write_conn_singleton,
    _get_singleton_conn_op_lock,
    _close_main_write_conn_singleton,
    _close_hub_write_conn_singleton,
    _is_main_db_path,
    _is_main_write_singleton_conn,
    _get_local_conn,
    HUB_DB_PATH,
)
from core.logger import get_logger

# 内部状态
_write_queue = queue.Queue(maxsize=10000)
_writer_daemon_thread: Optional[threading.Thread] = None
_writer_daemon_stop_event = threading.Event()
_writer_daemon_lock = threading.Lock()

_needs_sync = False
_last_write_time = 0.0
_sync_daemon_thread: Optional[threading.Thread] = None
_sync_daemon_stop_event = threading.Event()

_write_queue_stats = {
    "total_queued": 0,
    "total_written": 0,
    "total_errors": 0,
    "last_batch_size": 0,
}

# 慢阈值（毫秒）：批写超过此值会被打成 WARNING（Phase 4.5 P95<100ms 对齐）
_SLOW_BATCH_WRITE_MS = 100
# 同步线程 sync() 慢阈值：网络往返 + 远端 commit，>500ms 视为慢
_SLOW_SYNC_MS = 500

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
    try:
        # 【关键修复】使用具名游标执行，绝不能用 write_conn.execute
        cur.execute("BEGIN IMMEDIATE")
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
        write_conn.commit()
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
    conn_lock = _get_singleton_conn_op_lock(write_conn)
    started_at = time.time()

    while retry_count < max_retries:
        try:
            if conn_lock is None:
                _execute_batch_writes_unlocked(write_conn, batch)
            else:
                with conn_lock:
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
            # Catch ALL exceptions here to check for libsql WalConflicts
            error_msg = str(e).lower()
            is_wal_conflict = (
                "wal" in error_msg
                or "database is locked" in error_msg
                or "frame insert conflict" in error_msg
                or "walconflict" in error_msg
            )
            if is_wal_conflict and retry_count < max_retries - 1:
                retry_count += 1
                wait_time = 0.1 * (2 ** (retry_count - 1))
                _debug_log(
                    f"批量写入 WAL 冲突，等待 {wait_time*1000:.0f}ms 后重试 ({retry_count}/{max_retries}): {e}",
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

def _writer_daemon() -> None:
    global _needs_sync, _last_write_time

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
                    try:
                        write_conn = _get_dedicated_write_conn(_config.DB_PATH)
                        _execute_batch_writes(write_conn, pending_batch)
                        _write_queue_stats["total_written"] += len(pending_batch)
                        _write_queue_stats["last_batch_size"] = len(pending_batch)
                        pending_batch = []
                        last_commit_time = now
                        _needs_sync = True
                        _last_write_time = time.time()
                    except Exception as e:
                        _write_queue_stats["total_errors"] += 1
                        err_msg = str(e).lower()
                        
                        is_broken_conn = any(k in err_msg for k in [
                            "invalid state", "txn", "poison", "wal", "stream not found", "hrana"
                        ])
                        
                        if is_broken_conn:
                            _debug_log("检测到 Turso 云端连接休眠或底层状态失效，正在静默重建单例并重试...", level="INFO")
                            _close_main_write_conn_singleton()
                            time.sleep(0.5)
                            continue 
                        else:
                            _debug_log(f"后台写线程批量操作出错: {e}", level="ERROR")
                            pending_batch = []
                            
                        time.sleep(0.1)
            except Exception as e:
                _write_queue_stats["total_errors"] += 1
                _debug_log(f"后台写线程外层捕获出错: {e}", level="ERROR")
                time.sleep(0.1)

        if pending_batch:
            try:
                write_conn = _get_dedicated_write_conn(_config.DB_PATH)
                _execute_batch_writes(write_conn, pending_batch)
                _write_queue_stats["total_written"] += len(pending_batch)
                _needs_sync = True
                _last_write_time = time.time()
            except Exception as e:
                _write_queue_stats["total_errors"] += 1
                _debug_log(f"后台写线程关机批量操作出错: {e}", level="ERROR")

    except BaseException as e:
        _debug_log(f"后台写线程崩溃: {e}", level="CRITICAL")
    finally:
        _debug_log("后台写线程停止", level="INFO")

_SYNC_TIMEOUT_S = float(os.getenv("MOMO_SYNC_TIMEOUT_S", "3"))

def _sync_daemon() -> None:
    global _needs_sync, _last_write_time

    while not _sync_daemon_stop_event.is_set():
        time.sleep(2.0)

        if not _needs_sync:
            continue
        if (time.time() - _last_write_time) <= 5.0:
            continue

        try:
            conn = _get_main_write_conn_singleton(do_sync=False)
            if not hasattr(conn, "sync"):
                continue
            conn_lock = _get_singleton_conn_op_lock(conn)
            sync_started_at = time.time()

            # Phase D：在持锁窗口内限时执行 conn.sync()
            # 使用独立线程 + Event 实现软超时，避免 sync() 长时间阻塞锁
            sync_done = threading.Event()
            sync_error = [None]  # 用列表包装以支持闭包写入

            def _do_sync():
                try:
                    conn.sync()
                except Exception as e:
                    sync_error[0] = e
                finally:
                    sync_done.set()

            if conn_lock is not None:
                with conn_lock:
                    sync_thread = threading.Thread(target=_do_sync, daemon=True, name="MomoSyncOp")
                    sync_thread.start()
                    # 限时等待：超时后释放锁（with 块结束），sync 线程仍在后台完成
                    sync_done.wait(timeout=_SYNC_TIMEOUT_S)
            else:
                sync_thread = threading.Thread(target=_do_sync, daemon=True, name="MomoSyncOp")
                sync_thread.start()
                sync_done.wait(timeout=_SYNC_TIMEOUT_S)

            timed_out = not sync_done.is_set()
            if timed_out:
                _debug_log(
                    f"conn.sync() 超时 ({_SYNC_TIMEOUT_S}s)，已释放锁，sync 线程仍在后台完成",
                    level="WARNING",
                )
                # 等待 sync 线程自然结束（不设上限，但此时锁已释放不阻塞其他线程）
                sync_thread.join(timeout=30.0)

            if sync_error[0] is not None:
                raise sync_error[0]

            _needs_sync = False
            sync_duration_ms = int((time.time() - sync_started_at) * 1000)
            is_slow = sync_duration_ms >= _SLOW_SYNC_MS
            try:
                logger = get_logger()
                msg = f"idle_sync done | duration_ms={sync_duration_ms}"
                if timed_out:
                    msg += " | lock_released_early=true"
                kwargs = dict(
                    module="database.execution_engine",
                    duration_ms=sync_duration_ms,
                    is_slow=is_slow,
                )
                if is_slow:
                    logger.warning(msg + " | slow=true", **kwargs)
                else:
                    logger.info(msg, **kwargs)
            except Exception:
                pass
            # PLAYBOOK B5：写入指标层
            try:
                from core.metrics import get_metrics_collector
                from core.active_profile_registry import get_active
                get_metrics_collector().record(
                    get_active() or "_global",
                    "db.idle_sync.duration_ms",
                    float(sync_duration_ms),
                )
            except Exception:
                pass
        except BaseException as e:
            _debug_log(f"闲时后台自动同步失败: {e}", level="WARNING")

def _start_writer_daemon() -> None:
    global _writer_daemon_thread
    with _writer_daemon_lock:
        if _writer_daemon_thread is None or not _writer_daemon_thread.is_alive():
            _writer_daemon_stop_event.clear()
            _writer_daemon_thread = threading.Thread(target=_writer_daemon, daemon=True, name="MomoDBWriter")
            _writer_daemon_thread.start()
            _debug_log("后台写守护线程已启动", level="INFO")

def _start_sync_daemon() -> None:
    global _sync_daemon_thread
    with _writer_daemon_lock:
        if _sync_daemon_thread is None or not _sync_daemon_thread.is_alive():
            _sync_daemon_stop_event.clear()
            _sync_daemon_thread = threading.Thread(target=_sync_daemon, daemon=True, name="MomoDBSync")
            _sync_daemon_thread.start()
            _debug_log("后台同步守护线程已启动", level="INFO")

def _stop_writer_daemon(timeout_seconds: float = 2.0) -> None:
    global _writer_daemon_thread
    _writer_daemon_stop_event.set()
    if _writer_daemon_thread and _writer_daemon_thread.is_alive():
        _writer_daemon_thread.join(timeout=timeout_seconds)

def _stop_sync_daemon(timeout_seconds: float = 2.0) -> None:
    global _sync_daemon_thread
    _sync_daemon_stop_event.set()
    if _sync_daemon_thread and _sync_daemon_thread.is_alive():
        _sync_daemon_thread.join(timeout=timeout_seconds)

def _queue_write_operation(sql: str, args: Tuple = (), op_type: str = "insert_or_replace") -> bool:
    _start_writer_daemon()
    item = {"op_type": op_type, "sql": sql, "args": args}
    try:
        _write_queue.put(item, timeout=2.0)
        return True
    except queue.Full:
        _debug_log(f"写队列满，丢弃操作: {sql[:100]}", level="WARNING")
        return False

def _queue_batch_write_operation(sql: str, args_list: List[Tuple]) -> bool:
    if not args_list:
        return True
    _start_writer_daemon()
    item = {"op_type": "executemany", "sql": sql, "args_list": args_list}
    try:
        _write_queue.put(item, timeout=2.0)
        return True
    except queue.Full:
        _debug_log(f"写队列满，丢弃批量操作: {sql[:100]} | size={len(args_list)}", level="WARNING")
        return False

def init_concurrent_system() -> None:
    _start_writer_daemon()
    _start_sync_daemon()
    _debug_log("并发系统初始化完成", level="INFO")

def cleanup_concurrent_system() -> None:
    _stop_writer_daemon(timeout_seconds=5.0)
    _stop_sync_daemon(timeout_seconds=2.0)
    _close_main_write_conn_singleton()
    _close_hub_write_conn_singleton()
    _debug_log("并发系统清理完成", level="INFO")

def _release_db_file_handles_for_recovery(db_path: str) -> None:
    import os
    abs_path = os.path.abspath(db_path or _config.DB_PATH)
    try:
        _stop_sync_daemon(timeout_seconds=1.5)
    except Exception:
        pass
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
    global _needs_sync, _last_write_time
    if conn is not None:
        if not _is_main_write_singleton_conn(conn):
            return
    elif not _is_main_db_path(db_path):
        return

    _needs_sync = True
    _last_write_time = time.time()

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
