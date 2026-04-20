# =============================================================
# ⚠️ 弃用收口标记（DEPRECATION NOTICE）
# =============================================================
# 本文件仅保留兼容旧版数据库管理接口，所有新功能/逻辑请统一迁移至 database/ 分层实现。
# 后续开发请勿再向本文件添加任何新逻辑！如需扩展请在 database/ 下新建对应模块。
#
# 保持现有接口不破坏旧调用，后续如需移除请先全局替换依赖。
# =============================================================
"""
core/db_manager.py: 兼容旧版数据库管理接口，转发到新 database 分层实现。
"""
# -*- coding: utf-8 -*-
import sqlite3, os, json, re, hashlib, shutil, time, hmac, base64, threading, queue
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Tuple, List, Any, Callable
import requests
from urllib.parse import urlparse
from config import ACTIVE_USER, DB_PATH, TEST_DB_PATH, DATA_DIR, PROFILES_DIR, TURSO_HUB_DB_URL, TURSO_HUB_AUTH_TOKEN, HUB_DB_PATH, FORCE_CLOUD_MODE, ENCRYPTION_KEY

TURSO_DB_URL = None
TURSO_AUTH_TOKEN = None
TURSO_DB_HOSTNAME = None
TURSO_TEST_DB_URL = os.getenv('TURSO_TEST_DB_URL')
TURSO_TEST_AUTH_TOKEN = os.getenv('TURSO_TEST_AUTH_TOKEN')
TURSO_TEST_DB_HOSTNAME = os.getenv('TURSO_TEST_DB_HOSTNAME')

try:
    import libsql
    HAS_LIBSQL = True
except ImportError:
    HAS_LIBSQL = False
# 导入日志系统
try:
    from .logger import ContextLogger, log_performance, get_logger
    import logging
except ImportError:
    # 如果导入失败，提供简单的替代
    class ContextLogger:
        def __init__(self, logger): self.logger = logger
        def info(self, *args, **kwargs): pass
        def error(self, *args, **kwargs): pass
        def debug(self, *args, **kwargs): pass
    
    def log_performance(logger_func):
        def decorator(func):
            return func
        return decorator
    def get_logger():
        import logging
        return ContextLogger(logging.getLogger(__name__))

# 表存在状态缓存（避免重复检查）
_table_exists_cache = {}
_cloud_targets_cache = {"expire_at": 0.0, "targets": []}
_CLOUD_TARGET_CACHE_TTL_SECONDS = int(os.getenv("CLOUD_TARGET_CACHE_TTL_SECONDS", "600"))
_CLOUD_LOOKUP_MAX_TARGETS = int(os.getenv("CLOUD_LOOKUP_MAX_TARGETS", "40"))
_MGMT_TOKEN_VALIDATE_TTL_SECONDS = int(os.getenv("MGMT_TOKEN_VALIDATE_TTL_SECONDS", "300"))
_mgmt_token_validation_cache = {"expire_at": 0.0, "valid": None, "reason": ""}
_HUB_INIT_STATE_TTL_SECONDS = int(os.getenv("HUB_INIT_STATE_TTL_SECONDS", "600"))
_HUB_SCHEMA_VERSION = os.getenv("HUB_SCHEMA_VERSION", "1")
_hub_init_state_cache = {"expire_at": 0.0, "state": None}
_throttled_log_state = {}
_throttled_log_lock = threading.Lock()
UTC_PLUS_8 = timezone(timedelta(hours=8))

# ============ 高并发处理：读写分离 + 线程隔离 ============
# 指令 1: 读操作使用 ThreadLocal 存储，确保每个线程的专属读连接
_thread_local_read_conns = threading.local()  # ThreadLocal 读连接存储

# 指令 2: 写操作通过后台守护线程序列化，使用队列进行高并发缓冲
_write_queue = queue.Queue(maxsize=10000)  # 写入队列，最多缓存 10000 条
_writer_daemon_thread = None  # 后台写线程句柄
_writer_daemon_stop_event = threading.Event()  # 停止信号
_writer_daemon_lock = threading.Lock()  # 保证只启动一个写线程
_needs_sync = False  # 是否存在待同步的本地写入
_last_write_time = 0.0  # 最近一次成功写入时间戳
_sync_daemon_thread = None  # 后台同步线程句柄
_sync_daemon_stop_event = threading.Event()  # 后台同步停止信号
_main_write_conn_singleton = None  # 主库 Embedded Replica 写连接（全局单例）
_main_write_conn_lock = threading.Lock()  # 保护主库写连接单例
_main_write_conn_op_lock = threading.RLock()  # 串行化主库单例上的同步/提交/查询操作
_hub_write_conn_singleton = None  # Hub Embedded Replica 写连接（全局单例）
_hub_write_conn_lock = threading.Lock()  # 保护 Hub 写连接单例
_hub_write_conn_op_lock = threading.RLock()  # 串行化 Hub 单例上的同步/提交/查询操作

# 用于跟踪写入队列的统计
_write_queue_stats = {
    "total_queued": 0,
    "total_written": 0,
    "total_errors": 0,
    "last_batch_size": 0,
}

_throttled_log_state = {}
_throttled_log_lock = threading.Lock()
UTC_PLUS_8 = timezone(timedelta(hours=8))

def _get_table_exists_cache():
    """获取表存在状态缓存"""
    return _table_exists_cache


def _is_main_db_path(db_path: str = None) -> bool:
    """判断给定路径是否为主库路径。"""
    target = os.path.abspath(db_path or DB_PATH)
    return target == os.path.abspath(DB_PATH)


def _mark_main_db_needs_sync(db_path: str = None, conn: Any = None) -> None:
    """标记主库存在待同步写入，供后台防抖 sync 线程消费。"""
    global _needs_sync, _last_write_time

    if conn is not None:
        if not _is_main_write_singleton_conn(conn):
            return
    elif not _is_main_db_path(db_path):
        return

    _needs_sync = True
    _last_write_time = time.time()


def _close_main_write_conn_singleton() -> None:
    """关闭主库 Embedded Replica 写连接单例（进程退出时调用）。"""
    global _main_write_conn_singleton
    with _main_write_conn_lock:
        conn = _main_write_conn_singleton
        _main_write_conn_singleton = None

    if conn is None:
        return

    try:
        conn.close()
        _debug_log("主库 Embedded Replica 写连接单例已关闭", level="INFO")
    except Exception as e:
        _debug_log(f"关闭主库写连接单例失败: {e}", level="WARNING")


def _close_hub_write_conn_singleton() -> None:
    """关闭 Hub Embedded Replica 写连接单例（进程退出时调用）。"""
    global _hub_write_conn_singleton
    with _hub_write_conn_lock:
        conn = _hub_write_conn_singleton
        _hub_write_conn_singleton = None

    if conn is None:
        return

    try:
        conn.close()
        _debug_log("Hub Embedded Replica 写连接单例已关闭", level="INFO")
    except Exception as e:
        _debug_log(f"关闭 Hub 写连接单例失败: {e}", level="WARNING")


def _is_main_write_singleton_conn(conn: Any) -> bool:
    """判断连接是否为主库写连接单例。"""
    with _main_write_conn_lock:
        return conn is not None and conn is _main_write_conn_singleton


def _is_hub_write_singleton_conn(conn: Any) -> bool:
    """判断连接是否为 Hub 写连接单例。"""
    with _hub_write_conn_lock:
        return conn is not None and conn is _hub_write_conn_singleton


def _get_singleton_conn_op_lock(conn: Any):
    """返回单例连接对应的操作锁。"""
    if _is_main_write_singleton_conn(conn):
        return _main_write_conn_op_lock
    if _is_hub_write_singleton_conn(conn):
        return _hub_write_conn_op_lock
    return None


def _get_main_write_conn_singleton(do_sync: bool = False, max_retries: int = 3, retry_delay: float = 1.0) -> Any:
    """获取主库 Embedded Replica 写连接单例。

    约束：
    - 仅为主库创建一个带 sync_url 的连接，避免产生第二个 sync agent。
    - 连接在整个进程生命周期内复用，由 cleanup_concurrent_system 统一关闭。
    """
    global _main_write_conn_singleton

    ctx = _resolve_conn_context(DB_PATH)
    if not (ctx.get("url") and ctx.get("token") and HAS_LIBSQL):
        return _get_local_conn(DB_PATH)

    with _main_write_conn_lock:
        if _main_write_conn_singleton is not None:
            try:
                with _main_write_conn_op_lock:
                    _main_write_conn_singleton.execute("SELECT 1")
                    if do_sync and hasattr(_main_write_conn_singleton, 'sync'):
                        _main_write_conn_singleton.sync()
                return _main_write_conn_singleton
            except BaseException as health_error:
                _debug_log(f"主库写连接单例健康检查失败，准备重建: {health_error}", level="WARNING")
                try:
                    _main_write_conn_singleton.close()
                except Exception:
                    pass
                _main_write_conn_singleton = None

    last_error = None
    for attempt in range(max_retries):
        try:
            conn = _connect_embedded_replica(DB_PATH, ctx["url"], ctx["token"], do_sync=do_sync)
            with _main_write_conn_lock:
                if _main_write_conn_singleton is None:
                    _main_write_conn_singleton = conn
                    _debug_log("主库 Embedded Replica 写连接单例已创建", level="INFO")
                    return _main_write_conn_singleton

                # 并发下可能已有其他线程先创建，关闭当前新建连接并复用已有连接
                try:
                    conn.close()
                except Exception:
                    pass
                return _main_write_conn_singleton
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            break

    raise last_error or RuntimeError("无法创建主库 Embedded Replica 写连接单例")


def _get_hub_write_conn_singleton(do_sync: bool = False, max_retries: int = 3, retry_delay: float = 1.0) -> Any:
    """获取 Hub Embedded Replica 写连接单例。"""
    global _hub_write_conn_singleton

    if not (TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN and HAS_LIBSQL):
        return _get_hub_local_conn()

    with _hub_write_conn_lock:
        if _hub_write_conn_singleton is not None:
            try:
                with _hub_write_conn_op_lock:
                    _hub_write_conn_singleton.execute("SELECT 1")
                    if do_sync and hasattr(_hub_write_conn_singleton, 'sync'):
                        _hub_write_conn_singleton.sync()
                return _hub_write_conn_singleton
            except BaseException as health_error:
                _debug_log(f"Hub 写连接单例健康检查失败，准备重建: {health_error}", level="WARNING")
                try:
                    _hub_write_conn_singleton.close()
                except Exception:
                    pass
                _hub_write_conn_singleton = None

    last_error = None
    for attempt in range(max_retries):
        try:
            conn = _connect_embedded_replica(HUB_DB_PATH, TURSO_HUB_DB_URL, TURSO_HUB_AUTH_TOKEN, do_sync=do_sync)
            with _hub_write_conn_lock:
                if _hub_write_conn_singleton is None:
                    _hub_write_conn_singleton = conn
                    _debug_log("Hub Embedded Replica 写连接单例已创建", level="INFO")
                    return _hub_write_conn_singleton

                try:
                    conn.close()
                except Exception:
                    pass
                return _hub_write_conn_singleton
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            break

    raise last_error or RuntimeError("无法创建 Hub Embedded Replica 写连接单例")


# ============ 指令 1: ThreadLocal 读连接管理（禁止跨线程连接共享） ============
def _get_thread_local_read_conn(db_path: str = None) -> sqlite3.Connection:
    """获取当前线程专属的读连接（ThreadLocal 存储）。
    
    每个线程拥有且仅拥有一个读连接，避免多线程竞争导致的连接损坏。
    """
    path = db_path or DB_PATH
    # 使用路径作为 key，支持多个数据库的线程隔离
    cache_key = os.path.abspath(path)
    
    if not hasattr(_thread_local_read_conns, 'conns'):
        _thread_local_read_conns.conns = {}
    
    conns_dict = _thread_local_read_conns.conns
    cached_conn = conns_dict.get(cache_key)
    if cached_conn is not None:
        try:
            cached_conn.execute("SELECT 1")
            return cached_conn
        except BaseException as e:
            # libsql/PyO3 可能抛出 PanicException（BaseException），不能只捕获 Exception。
            _debug_log(f"ThreadLocal: 读连接健康检查失败，准备重建: {e}", level="WARNING")
            try:
                cached_conn.close()
            except Exception:
                pass
            conns_dict.pop(cache_key, None)

    if cache_key not in conns_dict or conns_dict[cache_key] is None:
        # 创建新的读连接
        conns_dict[cache_key] = _get_read_conn_impl(path)
        _debug_log(f"ThreadLocal: 为线程 {threading.current_thread().name} 创建读连接: {cache_key}")
    
    return conns_dict[cache_key]


def _cleanup_thread_local_read_conns():
    """清理当前线程的所有读连接（线程退出时调用）。"""
    if not hasattr(_thread_local_read_conns, 'conns'):
        return
    
    conns_dict = _thread_local_read_conns.conns
    for cache_key, conn in list(conns_dict.items()):
        if conn is not None:
            try:
                conn.close()
                _debug_log(f"ThreadLocal: 清理线程 {threading.current_thread().name} 的读连接: {cache_key}")
            except Exception as e:
                _debug_log(f"ThreadLocal: 关闭读连接出错: {e}", level="WARNING")
    
    conns_dict.clear()


def _release_db_file_handles_for_recovery(db_path: str) -> None:
    """在数据库损坏恢复前，尽力释放当前进程持有的文件句柄。"""
    abs_path = os.path.abspath(db_path or DB_PATH)

    # 0) 先停掉后台线程，避免其在恢复窗口重新占用数据库句柄
    try:
        _stop_sync_daemon(timeout_seconds=1.5)
    except Exception:
        pass
    try:
        _stop_writer_daemon(timeout_seconds=1.5)
    except Exception:
        pass

    # 1) 释放当前线程的 ThreadLocal 读连接（按路径定向）
    if hasattr(_thread_local_read_conns, 'conns'):
        conns_dict = _thread_local_read_conns.conns
        cached_conn = conns_dict.pop(abs_path, None)
        if cached_conn is not None:
            try:
                cached_conn.close()
                _debug_log(f"恢复前释放 ThreadLocal 读连接: {abs_path}", level="WARNING")
            except Exception as close_error:
                _debug_log(f"恢复前释放 ThreadLocal 读连接失败: {close_error}", level="WARNING")

    # 2) 释放全局写连接单例（防止 Windows 下 move/remove 失败）
    try:
        if abs_path == os.path.abspath(DB_PATH):
            _close_main_write_conn_singleton()
        if abs_path == os.path.abspath(HUB_DB_PATH):
            _close_hub_write_conn_singleton()
    except Exception as singleton_error:
        _debug_log(f"恢复前释放写连接单例失败: {singleton_error}", level="WARNING")


# ============ 指令 2: 后台写线程 + 异步队列（序列化所有写操作） ============
def _get_dedicated_write_conn(db_path: str = None) -> sqlite3.Connection:
    """获取后台写线程专用的写连接。
    
    此连接只在后台写守护线程中使用，不暴露给用户代码。
    保证写操作的单线程序列化。
    """
    path = db_path or DB_PATH
    return _get_main_write_conn_singleton(do_sync=False)


def _writer_daemon():
    """后台写守护线程：从队列消费数据，执行批量写入。
    
    特点：
    - 独占一个写连接（不与其他线程共享）
    - 每积攒 N 条或超时 1 秒，执行一次批量提交
    - 所有 INSERT/UPDATE 通过此线程序列化处理
    """
    batch_threshold = 50  # 积攒多少条数据后执行批量提交
    timeout_seconds = 1.0  # 超时时间
    
    global _needs_sync, _last_write_time

    write_conn = None
    pending_batch = []
    last_commit_time = time.time()
    
    try:
        write_conn = _get_dedicated_write_conn(DB_PATH)
        _debug_log("后台写线程启动", level="INFO")
        
        while True:
            # 停机时必须先排空队列并提交内存批次，避免 processed_words 等去重状态丢失。
            if _writer_daemon_stop_event.is_set() and _write_queue.empty() and not pending_batch:
                break
            try:
                # 从队列取数据，超时 100ms
                try:
                    item = _write_queue.get(timeout=0.1)
                    pending_batch.append(item)
                    _write_queue_stats["total_queued"] += 1
                except queue.Empty:
                    pass
                
                # 决定是否提交：达到阈值或超时
                now = time.time()
                should_commit = (
                    len(pending_batch) >= batch_threshold or
                    (pending_batch and (now - last_commit_time) >= timeout_seconds) or
                    (_writer_daemon_stop_event.is_set() and pending_batch)
                )
                
                if should_commit and pending_batch:
                    try:
                        _execute_batch_writes(write_conn, pending_batch)
                        _write_queue_stats["total_written"] += len(pending_batch)
                        _write_queue_stats["last_batch_size"] = len(pending_batch)
                        last_commit_time = now
                        _needs_sync = True
                        _last_write_time = time.time()
                        pending_batch = []
                    except sqlite3.OperationalError as batch_e:
                        # WAL冲突或其他操作错误 - 重试逻辑已在_execute_batch_writes中处理
                        # 这里只是为了额外的日志和恢复机制
                        error_msg = str(batch_e).lower()
                        is_wal_conflict = "wal" in error_msg or "database is locked" in error_msg
                        if is_wal_conflict:
                            _debug_log(f"后台写线程 WAL 冲突重试已失败，队列回补待重试: {batch_e}", level="WARNING")
                            # 保持batch等待下一次重试，不清空
                            time.sleep(0.5)
                        else:
                            _debug_log(f"后台写线程批量操作出错: {batch_e}", level="ERROR")
                            _write_queue_stats["total_errors"] += 1
                            pending_batch = []
                            time.sleep(0.1)
            
            except Exception as e:
                _debug_log(f"后台写线程批量操作出错: {e}", level="ERROR")
                _write_queue_stats["total_errors"] += 1
                pending_batch = []
                time.sleep(0.1)
        
        # 程序退出时，提交剩余数据
        if pending_batch:
            _execute_batch_writes(write_conn, pending_batch)
            _write_queue_stats["total_written"] += len(pending_batch)
            _needs_sync = True
            _last_write_time = time.time()
    
    except BaseException as e:
        _debug_log(f"后台写线程崩溃: {e}", level="CRITICAL")
    
    finally:
        # 主库写连接单例由 cleanup_concurrent_system 统一关闭，避免运行期重建第二个 sync agent
        if write_conn and not _is_main_write_singleton_conn(write_conn):
            try:
                write_conn.close()
            except Exception:
                pass
        _debug_log("后台写线程停止", level="INFO")


def _execute_batch_writes(write_conn: sqlite3.Connection, batch: List[Dict[str, Any]]) -> None:
    """执行批量写入操作，一次事务提交所有数据，支持WAL冲突重试。"""
    if not batch:
        return
    
    max_retries = 3
    retry_count = 0
    last_error = None
    conn_lock = _get_singleton_conn_op_lock(write_conn)
    
    while retry_count < max_retries:
        try:
            lock_ctx = conn_lock if conn_lock is not None else None
            if lock_ctx is None:
                _execute_batch_writes_unlocked(write_conn, batch)
                return

            with lock_ctx:
                _execute_batch_writes_unlocked(write_conn, batch)
            return

        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            is_wal_conflict = "wal" in error_msg or "database is locked" in error_msg or "frame insert conflict" in error_msg

            if is_wal_conflict and retry_count < max_retries - 1:
                retry_count += 1
                wait_time = 0.1 * (2 ** (retry_count - 1))
                _debug_log(f"批量写入WAL冲突，等待 {wait_time*1000:.0f}ms 后重试 ({retry_count}/{max_retries}): {e}", level="WARNING")
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
            _debug_log(f"批量写入失败: {e}", level="ERROR")
            raise

        except Exception as e:
            try:
                write_conn.rollback()
            except Exception:
                pass
            _debug_log(f"批量写入失败: {e}", level="ERROR")
            raise
    
    # 如果退出循环仍有错误，抛出最后一个错误
    if last_error:
        _debug_log(f"批量写入在 {max_retries} 次重试后仍失败: {last_error}", level="ERROR")
        raise last_error


def _execute_batch_writes_unlocked(write_conn: sqlite3.Connection, batch: List[Dict[str, Any]]) -> None:
    """真正执行批量写入的事务逻辑（不负责锁）。"""
    write_conn.execute("BEGIN TRANSACTION")
    cur = write_conn.cursor()

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
        # 可扩展其他操作类型

    write_conn.commit()


def _start_writer_daemon():
    """启动后台写守护线程（若未启动）。"""
    global _writer_daemon_thread
    
    with _writer_daemon_lock:
        if _writer_daemon_thread is None or not _writer_daemon_thread.is_alive():
            _writer_daemon_stop_event.clear()
            _writer_daemon_thread = threading.Thread(target=_writer_daemon, daemon=True, name="MomoDBWriter")
            _writer_daemon_thread.start()
            _debug_log("后台写守护线程已启动", level="INFO")


def _sync_daemon():
    """后台同步守护线程：在写入空闲一段时间后自动执行 sync()。"""
    global _needs_sync, _last_write_time

    while not _sync_daemon_stop_event.is_set():
        time.sleep(2.0)

        if not _needs_sync:
            continue

        if (time.time() - _last_write_time) <= 5.0:
            continue

        try:
            conn = _get_main_write_conn_singleton(do_sync=False)
            if not hasattr(conn, 'sync'):
                continue

            with _main_write_conn_op_lock:
                conn.sync()
            _needs_sync = False
            _debug_log("闲时后台自动同步完成", level="INFO")
        except BaseException as e:
            _debug_log(f"闲时后台自动同步失败: {e}", level="WARNING")


def _start_sync_daemon():
    """启动后台同步守护线程（若未启动）。"""
    global _sync_daemon_thread

    with _writer_daemon_lock:
        if _sync_daemon_thread is None or not _sync_daemon_thread.is_alive():
            _sync_daemon_stop_event.clear()
            _sync_daemon_thread = threading.Thread(target=_sync_daemon, daemon=True, name="MomoDBSync")
            _sync_daemon_thread.start()
            _debug_log("后台同步守护线程已启动", level="INFO")


def _stop_sync_daemon(timeout_seconds: float = 2.0):
    """停止后台同步守护线程（程序退出时调用）。"""
    global _sync_daemon_thread

    _sync_daemon_stop_event.set()
    if _sync_daemon_thread and _sync_daemon_thread.is_alive():
        _sync_daemon_thread.join(timeout=timeout_seconds)
        _debug_log("后台同步守护线程已停止", level="INFO")


def _stop_writer_daemon(timeout_seconds: float = 2.0):
    """停止后台写守护线程（程序退出时调用）。"""
    global _writer_daemon_thread
    
    _writer_daemon_stop_event.set()
    if _writer_daemon_thread and _writer_daemon_thread.is_alive():
        _writer_daemon_thread.join(timeout=timeout_seconds)
        if _writer_daemon_thread.is_alive():
            _debug_log(
                f"后台写守护线程停止超时（{timeout_seconds:.1f}s），队列剩余约 {_write_queue.qsize()} 条",
                level="WARNING",
            )
        else:
            _debug_log("后台写守护线程已停止", level="INFO")


def _queue_write_operation(sql: str, args: Tuple = (), op_type: str = "insert_or_replace") -> bool:
    """将写操作加入队列（异步处理）。
    
    高并发业务线程调用此函数，仅执行 queue.put()，立即返回。
    """
    _start_writer_daemon()  # 确保写线程已启动
    
    item = {
        "op_type": op_type,
        "sql": sql,
        "args": args,
    }
    
    try:
        _write_queue.put(item, timeout=2.0)
        return True
    except queue.Full:
        _debug_log(f"写队列满，丢弃操作: {sql[:100]}", level="WARNING")
        return False


def _queue_batch_write_operation(sql: str, args_list: List[Tuple]) -> bool:
    """将批量写操作加入队列（异步处理）。"""
    if not args_list:
        return True

    _start_writer_daemon()
    item = {
        "op_type": "executemany",
        "sql": sql,
        "args_list": args_list,
    }

    try:
        _write_queue.put(item, timeout=2.0)
        return True
    except queue.Full:
        _debug_log(f"写队列满，丢弃批量操作: {sql[:100]} | size={len(args_list)}", level="WARNING")
        return False


def _hash_fingerprint(raw: str) -> str:
    """将连接标识压缩成短哈希，避免 marker 文件名过长。"""
    return hashlib.sha256((raw or "unknown").encode("utf-8")).hexdigest()[:12]

def _main_db_fingerprint(db_path: str = None) -> str:
    """主数据库实例指纹：优先云端 URL，其次本地绝对路径。"""
    is_test = db_path and 'test_' in os.path.basename(db_path)
    url = TURSO_TEST_DB_URL if is_test else TURSO_DB_URL
    if not url:
        hostname = TURSO_TEST_DB_HOSTNAME if is_test else TURSO_DB_HOSTNAME
        if hostname:
            url = _normalize_turso_url(hostname)
    if url:
        return f"cloud:{url.strip()}"
    path = os.path.abspath(db_path or DB_PATH)
    return f"local:{path}"

def _hub_db_fingerprint() -> str:
    """Hub 数据库实例指纹。"""
    if TURSO_HUB_DB_URL:
        return f"cloud:{TURSO_HUB_DB_URL.strip()}"
    return f"local:{os.path.abspath(HUB_DB_PATH)}"


def _hub_init_state_path() -> str:
    marker_dir = os.path.join(DATA_DIR, "db_init_markers")
    os.makedirs(marker_dir, exist_ok=True)
    return os.path.join(marker_dir, "hub_init_state.json")


def _load_hub_init_state(force_refresh: bool = False) -> Optional[dict]:
    now = time.time()
    if not force_refresh and _hub_init_state_cache.get("state") and now < _hub_init_state_cache.get("expire_at", 0.0):
        return _hub_init_state_cache["state"]

    path = _hub_init_state_path()
    if not os.path.exists(path):
        _hub_init_state_cache["state"] = None
        _hub_init_state_cache["expire_at"] = now + _HUB_INIT_STATE_TTL_SECONDS
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        if isinstance(state, dict):
            _hub_init_state_cache["state"] = state
            _hub_init_state_cache["expire_at"] = now + _HUB_INIT_STATE_TTL_SECONDS
            return state
    except Exception as e:
        _debug_log(f"读取 Hub 初始化状态失败: {e}")

    _hub_init_state_cache["state"] = None
    _hub_init_state_cache["expire_at"] = now + _HUB_INIT_STATE_TTL_SECONDS
    return None


def _save_hub_init_state(state: dict) -> None:
    path = _hub_init_state_path()
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        _hub_init_state_cache["state"] = state
        _hub_init_state_cache["expire_at"] = time.time() + _HUB_INIT_STATE_TTL_SECONDS
    except Exception as e:
        _debug_log(f"保存 Hub 初始化状态失败: {e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _hub_init_state_is_fresh(hub_fp: str) -> bool:
    state = _load_hub_init_state()
    if not state:
        return False

    if state.get("hub_fp") != hub_fp:
        return False
    if state.get("schema_version") != _HUB_SCHEMA_VERSION:
        return False

    last_success_at = float(state.get("last_success_at", 0.0) or 0.0)
    if not last_success_at:
        return False

    return (time.time() - last_success_at) <= _HUB_INIT_STATE_TTL_SECONDS

def _get_db_init_marker_path(db_type: str, db_fingerprint: str = None) -> str:
    """获取数据库初始化标记文件路径"""
    marker_dir = os.path.join(DATA_DIR, "db_init_markers")
    os.makedirs(marker_dir, exist_ok=True)
    if db_fingerprint:
        digest = _hash_fingerprint(db_fingerprint)
        return os.path.join(marker_dir, f"{db_type}_{digest}_initialized.flag")
    return os.path.join(marker_dir, f"{db_type}_initialized.flag")

def _is_db_initialized(db_type: str, db_fingerprint: str = None) -> bool:
    """检查数据库是否已经初始化（通过本地标记文件）"""
    marker_path = _get_db_init_marker_path(db_type, db_fingerprint)
    return os.path.exists(marker_path)

def _mark_db_initialized(db_type: str, db_fingerprint: str = None):
    """标记数据库已初始化"""
    marker_path = _get_db_init_marker_path(db_type, db_fingerprint)
    with open(marker_path, 'w') as f:
        f.write(f"initialized at {time.time()}")

def _check_table_exists(cursor, table_name: str, db_type: str = "main", cache_scope: str = None) -> bool:
    """检查表是否存在，使用缓存避免重复查询

    Args:
        cursor: 数据库游标
        table_name: 表名
        db_type: 数据库类型 ("main" 或 "hub")
    """
    # 使用数据库类型 + 连接作用域 + 表名作为缓存键，避免跨库误复用
    scope = cache_scope or "default"
    cache_key = f"{db_type}_{scope}_{table_name}"

    # 检查缓存
    if cache_key in _table_exists_cache:
        return _table_exists_cache[cache_key]

    # 执行查询
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    exists = cursor.fetchone() is not None

    # 更新缓存
    _table_exists_cache[cache_key] = exists
    return exists

def _debug_log(msg, start_time=None, level="DEBUG", module="db_manager"):
    """利用现有日志系统的可分级调试函数
    
    Args:
        msg: 日志消息
        start_time: 操作开始时间（用于计算耗时）
        level: 日志级别 ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
        module: 模块名称（用于模块级别过滤）
    """
    
    # 计算耗时
    elapsed = f' | Time: {int((time.time() - start_time)*1000)}ms' if start_time else ''
    log_msg = f"{msg}{elapsed}"
    
    try:
        logger = get_logger()
        level_map = {
            "CRITICAL": logger.critical,
            "ERROR": logger.error,
            "WARNING": logger.warning,
            "INFO": logger.info,
            "DEBUG": logger.debug,
        }
        
        log_func = level_map.get(level, logger.debug)
        log_func(log_msg, module=module)
    except Exception:
        # 如果日志失败，忽略错误，避免影响主流程
        pass


def _debug_log_throttled(key: str, msg: str, interval_seconds: float = 30.0, start_time=None, level="DEBUG", module="db_manager"):
    """按 key 对高频日志进行限频，减少重复刷屏。"""
    now = time.time()
    should_log = False
    with _throttled_log_lock:
        last_ts = float(_throttled_log_state.get(key, 0.0) or 0.0)
        if now - last_ts >= float(interval_seconds):
            _throttled_log_state[key] = now
            should_log = True

    if should_log:
        _debug_log(msg, start_time=start_time, level=level, module=module)

def _read_profile_cloud_config(profile_env_path: str) -> Optional[Dict[str, str]]:
    """Read TURSO DB URL/token from a profile env file without mutating process env."""
    if not os.path.exists(profile_env_path):
        return None

    url = ""
    token = ""
    try:
        with open(profile_env_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key == "TURSO_DB_URL":
                    url = value
                elif key == "TURSO_AUTH_TOKEN":
                    token = value
        if url and token:
            return {"url": url, "token": token}
    except Exception as e:
        _debug_log(f"读取 profile 云配置失败: {profile_env_path} -> {e}")
    return None

def _validate_turso_management_token(force_refresh: bool = False) -> Dict[str, Any]:
    """Validate Turso management token once per TTL to avoid repeated slow failures."""
    now = time.time()
    mgmt_token = (os.getenv("TURSO_MGMT_TOKEN") or "").strip()
    if not mgmt_token:
        return {"checked": False, "valid": False, "reason": "missing-mgmt-token"}

    if not force_refresh and _mgmt_token_validation_cache.get("valid") is not None and now < _mgmt_token_validation_cache.get("expire_at", 0.0):
        return {
            "checked": True,
            "valid": bool(_mgmt_token_validation_cache.get("valid")),
            "reason": _mgmt_token_validation_cache.get("reason", "cached"),
            "cached": True,
        }

    headers = {"Authorization": f"Bearer {mgmt_token}"}
    validate_url = "https://api.turso.tech/v1/auth/validate"
    fallback_validate_url = "https://api.turso.tech/v1/user"
    try:
        started_at = time.time()
        resp = requests.get(validate_url, headers=headers, timeout=6)
        elapsed_ms = int((time.time() - started_at) * 1000)

        if resp.status_code == 200:
            _mgmt_token_validation_cache["valid"] = True
            _mgmt_token_validation_cache["reason"] = "ok"
            _mgmt_token_validation_cache["expire_at"] = now + _MGMT_TOKEN_VALIDATE_TTL_SECONDS
            _debug_log(f"Turso 管理令牌校验通过 (/auth/validate) | validate_ms={elapsed_ms}")
            return {"checked": True, "valid": True, "reason": "ok", "cached": False}

        # 兼容不同 token 类型与后端能力差异：主校验失败时回退 /v1/user
        fallback_started_at = time.time()
        fallback_resp = requests.get(fallback_validate_url, headers=headers, timeout=6)
        fallback_elapsed_ms = int((time.time() - fallback_started_at) * 1000)
        if fallback_resp.status_code == 200:
            _mgmt_token_validation_cache["valid"] = True
            _mgmt_token_validation_cache["reason"] = "ok-fallback-user"
            _mgmt_token_validation_cache["expire_at"] = now + _MGMT_TOKEN_VALIDATE_TTL_SECONDS
            _debug_log(
                "Turso 管理令牌校验通过 (/auth/validate 失败后回退 /user) "
                f"| validate_ms={elapsed_ms}, fallback_ms={fallback_elapsed_ms}"
            )
            return {"checked": True, "valid": True, "reason": "ok-fallback-user", "cached": False}

        reason = f"auth-validate-http-{resp.status_code};fallback-http-{fallback_resp.status_code}"
        _mgmt_token_validation_cache["valid"] = False
        _mgmt_token_validation_cache["reason"] = reason
        _mgmt_token_validation_cache["expire_at"] = now + _MGMT_TOKEN_VALIDATE_TTL_SECONDS
        _debug_log(
            "Turso 管理令牌校验失败: "
            f"{reason} | validate_ms={elapsed_ms}, fallback_ms={fallback_elapsed_ms}"
        )
        return {"checked": True, "valid": False, "reason": reason, "cached": False}
    except Exception as e:
        reason = f"validate-error:{e}"
        _mgmt_token_validation_cache["valid"] = False
        _mgmt_token_validation_cache["reason"] = reason
        _mgmt_token_validation_cache["expire_at"] = now + _MGMT_TOKEN_VALIDATE_TTL_SECONDS
        _debug_log(f"Turso 管理令牌校验异常: {e}")
        return {"checked": True, "valid": False, "reason": reason, "cached": False}

def _fetch_turso_cloud_targets_via_api() -> List[Tuple[str, str, str]]:
    """Use Turso management API to discover history databases and generate DB auth tokens."""
    started_at = time.time()
    mgmt_token = (os.getenv("TURSO_MGMT_TOKEN") or "").strip()
    org_slug = (os.getenv("TURSO_ORG_SLUG") or "").strip()
    if not mgmt_token or not org_slug:
        return []

    validation = _validate_turso_management_token()
    if not validation.get("valid"):
        _debug_log(f"Turso API 云库发现跳过：管理令牌不可用 ({validation.get('reason')})")
        return []

    headers = {"Authorization": f"Bearer {mgmt_token}", "Content-Type": "application/json"}
    list_url = f"https://api.turso.tech/v1/organizations/{org_slug}/databases"
    try:
        list_started_at = time.time()
        resp = requests.get(list_url, headers=headers, timeout=12)
        list_elapsed_ms = int((time.time() - list_started_at) * 1000)
        if resp.status_code != 200:
            _debug_log(f"Turso API 获取数据库列表失败: {resp.status_code} | list_ms={list_elapsed_ms}")
            return []

        dbs = resp.json().get("databases", [])
        targets: List[Tuple[str, str, str]] = []
        history_candidates = 0
        token_elapsed_total_ms = 0
        for db in dbs:
            db_name = (db.get("Name") or db.get("name") or "").strip()
            if not db_name.startswith("history-") and not db_name.startswith("history_"):
                continue
            history_candidates += 1

            hostname = (db.get("Hostname") or db.get("hostname") or "").strip()
            db_url = _normalize_turso_url(hostname)
            if not db_url:
                continue

            token_url = f"https://api.turso.tech/v1/organizations/{org_slug}/databases/{db_name}/auth/tokens"
            token_started_at = time.time()
            token_resp = requests.post(token_url, headers=headers, json={}, timeout=12)
            token_elapsed_ms = int((time.time() - token_started_at) * 1000)
            token_elapsed_total_ms += token_elapsed_ms
            if token_resp.status_code not in (200, 201):
                _debug_log(f"Turso API 生成数据库令牌失败: {db_name} ({token_resp.status_code}) | token_ms={token_elapsed_ms}")
                continue

            token_json = token_resp.json() if token_resp.text else {}
            db_token = (token_json.get("jwt") or token_json.get("token") or "").strip()
            if not db_token:
                continue

            targets.append((db_url, db_token, f"云端数据库({db_name})"))

        total_elapsed_ms = int((time.time() - started_at) * 1000)
        _debug_log(
            "Turso API 云库发现完成: "
            f"db_total={len(dbs)}, history_candidates={history_candidates}, discovered={len(targets)} "
            f"| list_ms={list_elapsed_ms}, token_total_ms={token_elapsed_total_ms}, total_ms={total_elapsed_ms}"
        )
        return targets
    except Exception as e:
        total_elapsed_ms = int((time.time() - started_at) * 1000)
        _debug_log(f"Turso API 云库发现失败: {e} | total_ms={total_elapsed_ms}")
        return []

def _get_cached_turso_cloud_targets() -> List[Tuple[str, str, str]]:
    """Cache Turso API discovery result to reduce management API overhead."""
    now = time.time()
    cached_targets = _cloud_targets_cache.get("targets", [])
    if cached_targets and now < _cloud_targets_cache.get("expire_at", 0.0):
        ttl_left = int(_cloud_targets_cache.get("expire_at", 0.0) - now)
        _debug_log(f"Turso API 云库目标缓存命中: {len(cached_targets)} 个，TTL 剩余约 {ttl_left}s")
        return list(cached_targets)

    fresh_targets = _fetch_turso_cloud_targets_via_api()
    _cloud_targets_cache["targets"] = list(fresh_targets)
    _cloud_targets_cache["expire_at"] = now + _CLOUD_TARGET_CACHE_TTL_SECONDS
    _debug_log(f"Turso API 云库目标缓存刷新: {len(fresh_targets)} 个，TTL={_CLOUD_TARGET_CACHE_TTL_SECONDS}s")
    return fresh_targets

def _get_secret_key_bytes() -> bytes:
    """Derive symmetric key from ENCRYPTION_KEY. Empty result means secret storage disabled."""
    raw = (ENCRYPTION_KEY or "").strip()
    if not raw:
        return b""
    return hashlib.sha256(raw.encode("utf-8")).digest()

def _encrypt_secret_value(secret: str) -> str:
    key = _get_secret_key_bytes()
    if not key:
        raise ValueError("ENCRYPTION_KEY 未配置，无法加密敏感信息")

    plain = (secret or "").encode("utf-8")
    nonce = os.urandom(16)
    stream = bytearray()
    counter = 0
    while len(stream) < len(plain):
        stream.extend(hashlib.sha256(key + nonce + counter.to_bytes(4, "big")).digest())
        counter += 1

    cipher = bytes(p ^ s for p, s in zip(plain, stream[:len(plain)]))
    sig = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    blob = base64.urlsafe_b64encode(nonce + sig + cipher).decode("ascii")
    return f"v1:{blob}"

def _decrypt_secret_value(secret_blob: str) -> str:
    key = _get_secret_key_bytes()
    if not key:
        raise ValueError("ENCRYPTION_KEY 未配置，无法解密敏感信息")

    if not secret_blob:
        return ""
    if not str(secret_blob).startswith("v1:"):
        raise ValueError("不支持的密文版本")

    raw = base64.urlsafe_b64decode(secret_blob[3:].encode("ascii"))
    if len(raw) < 48:
        raise ValueError("密文长度非法")

    nonce = raw[:16]
    sig = raw[16:48]
    cipher = raw[48:]
    expect = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expect):
        raise ValueError("密文签名校验失败")

    stream = bytearray()
    counter = 0
    while len(stream) < len(cipher):
        stream.extend(hashlib.sha256(key + nonce + counter.to_bytes(4, "big")).digest())
        counter += 1

    plain = bytes(c ^ s for c, s in zip(cipher, stream[:len(cipher)]))
    return plain.decode("utf-8")

def _collect_cloud_lookup_targets() -> List[Tuple[str, str, str]]:
    """Collect unique cloud targets with API-first discovery.

    Returns:
        list[(url, token, source_label)]
    """
    targets: List[Tuple[str, str, str]] = []
    seen_urls = set()

    def _append_target(url: str, token: str, source: str):
        nurl = (url or "").strip()
        ntoken = (token or "").strip()
        if not nurl or not ntoken or nurl in seen_urls:
            return
        seen_urls.add(nurl)
        targets.append((nurl, ntoken, source))

    # 0. 当前用户云库始终优先
    _append_target(TURSO_DB_URL, TURSO_AUTH_TOKEN, "云端数据库(当前用户)")

    # 1. 优先通过 Turso 管理 API 发现数据库（避免完全依赖本地 env）
    for db_url, db_token, source_label in _get_cached_turso_cloud_targets():
        _append_target(db_url, db_token, source_label)

    # 2. 回退到本地 profiles 配置
    try:
        profile_files = sorted([f for f in os.listdir(PROFILES_DIR) if f.endswith(".env")])
    except Exception as e:
        _debug_log(f"扫描 profiles 目录失败: {e}")
        profile_files = []

    for env_file in profile_files:
        profile_name = os.path.splitext(env_file)[0]
        env_path = os.path.join(PROFILES_DIR, env_file)
        cfg = _read_profile_cloud_config(env_path)
        if not cfg:
            continue

        _append_target(cfg["url"], cfg["token"], f"云端数据库({profile_name})")

    if len(targets) > _CLOUD_LOOKUP_MAX_TARGETS:
        _debug_log(f"云库目标数量过多，已限制为前 {_CLOUD_LOOKUP_MAX_TARGETS} 个")
        targets = targets[:_CLOUD_LOOKUP_MAX_TARGETS]

    return targets

def get_timestamp_with_tz() -> str:
    """获取当前时间戳，格式为 ISO 8601 含时区。"""
    return datetime.now(UTC_PLUS_8).isoformat()

def generate_user_id(username: str) -> str:
    """统一用户 ID 生成算法：SHA256(username) 的前 16 位"""
    import hashlib
    normalized = username.strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]

def clean_for_maimemo(text: str) -> str:
    if text is None: return ''
    text = re.sub(r'^#{1,6}\s+', '', str(text), flags=re.MULTILINE)
    text = re.sub(r'^[\-\*]\s+', '• ', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\*(.+?)\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'`(.+?)`', r'\1', text)
    return text.strip()

def _is_sqlite_malformed_error(error: Exception) -> bool:
    """判断是否为本地 SQLite 文件损坏。"""
    msg = str(error or "").lower()
    return (
        "database disk image is malformed" in msg
        or "file is not a database" in msg
        or "malformed" in msg
    )


def _is_sqlite_row_decode_error(error: Exception) -> bool:
    """判断是否为 SQLite 文本列解码异常（历史脏数据/损坏字节）。"""
    msg = str(error or "").lower()
    return "could not decode to utf-8" in msg or ("utf-8" in msg and "decode" in msg)


def _is_sqlite_data_corruption_error(error: Exception) -> bool:
    """统一判断会导致查询失败的本地数据损坏/解码异常。"""
    return _is_sqlite_malformed_error(error) or _is_sqlite_row_decode_error(error)


def _backup_broken_database_file(db_path: str, warning_message: str) -> Optional[str]:
    """备份损坏的本地数据库文件，保留现场以便后续排查。"""
    try:
        abs_path = os.path.abspath(db_path)
        if not os.path.exists(abs_path):
            return None

        day_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
        backup_path = f"{abs_path}.er-broken-{day_tag}.bak"
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except Exception:
                pass

        moved = False
        last_error = None
        for attempt in range(3):
            try:
                shutil.move(abs_path, backup_path)
                moved = True
                break
            except OSError as move_error:
                last_error = move_error
                winerror = getattr(move_error, "winerror", None)
                if winerror == 32 or "being used by another process" in str(move_error).lower():
                    time.sleep(0.3 * (attempt + 1))
                    continue
                raise

        if not moved:
            try:
                shutil.copy2(abs_path, backup_path)
                removed_source = False
                try:
                    os.remove(abs_path)
                    removed_source = True
                except Exception:
                    _debug_log(
                        f"备份损坏数据库后无法删除源文件（可能仍被占用）: {abs_path}",
                        level="WARNING",
                    )
                if not removed_source:
                    return None
            except Exception as copy_error:
                if last_error:
                    _debug_log(f"备份损坏数据库失败: {last_error}", level="WARNING")
                _debug_log(f"备份损坏数据库失败: {copy_error}", level="WARNING")
                return None

        # 指令 3: 禁止删除 WAL 元数据文件
        # 在多线程和 WAL 模式下，强行删除 -wal, -shm, -info 文件是导致主库损坏的直接原因。
        # 备份主文件后，让 SQLite 的恢复机制自行处理元数据文件。
        _debug_log(
            f"{warning_message}: {backup_path}\n"
            f"注意：副本文件已备份，但相关 WAL 元数据未删除（避免多线程竞争导致损坏）",
            level="WARNING"
        )
        return backup_path
    except Exception as backup_error:
        _debug_log(f"备份损坏数据库失败: {backup_error}", level="WARNING")
        return None


def _get_local_conn(db_path: str = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def _open_local_connection() -> sqlite3.Connection:
        conn = sqlite3.connect(path, timeout=20.0)  # 增加超时时间以解决多线程死锁
        conn.row_factory = sqlite3.Row
        conn.text_factory = lambda b: b.decode("utf-8", "replace")
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")  # 5秒自动重试WAL锁定冲突
        conn.execute("PRAGMA wal_autocheckpoint=1000;")  # 每1000页自动checkpoint
        return conn

    try:
        return _open_local_connection()
    except (sqlite3.DatabaseError, sqlite3.OperationalError) as error:
        if not _is_sqlite_malformed_error(error):
            raise

        backup_path = _backup_broken_database_file(path, "检测到本地数据库损坏，已备份本地数据库")
        if not backup_path:
            raise

        if HAS_LIBSQL and TURSO_DB_URL and TURSO_AUTH_TOKEN:
            try:
                _debug_log(f"本地数据库损坏后，尝试通过云端副本重建: {path}", level="WARNING")
                return _get_conn(path, allow_local_fallback=False)
            except Exception as recovery_error:
                _debug_log(f"通过云端副本重建本地数据库失败，改为重新初始化空库: {recovery_error}", level="WARNING")

        conn = _open_local_connection()
        try:
            _create_tables(conn.cursor())
            conn.commit()
        except Exception as init_error:
            try:
                conn.close()
            except Exception:
                pass
            raise RuntimeError(f"本地数据库重建失败: {init_error}")
        return conn


def _get_libsql_local_read_conn(db_path: str) -> Any:
    """
    Open a pure-local connection using libsql (WITHOUT a sync_url).
    This safely reads the Embedded Replica without spawning a new Sync Agent
    and without letting native SQLite destroy the WAL metadata.
    """
    try:
        conn = libsql.connect(db_path)
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn
    except Exception as e:
        raise RuntimeError(f"Failed to create libsql local read connection: {e}")


def _normalize_turso_url(hostname: str) -> str:
    """Normalize Turso endpoint to sync_url format expected by libsql."""
    if not hostname:
        return ''
    raw = hostname.strip()
    # libsql.connect() 的 sync_url 参数接受标准 URL 格式
    if raw.startswith('libsql://') or raw.startswith('https://') or raw.startswith('wss://'):
        return raw
    # 如果是纯主机名，构造成 libsql:// URL
    if '.' in raw or raw == 'localhost':
        return f'libsql://{raw}'
    # 默认添加 libsql:// scheme
    return f'libsql://{raw}'


def _is_replica_metadata_missing_error(error: Exception) -> bool:
    """判断是否为 Embedded Replica 本地状态损坏（db 存在但 metadata 缺失）。"""
    msg = str(error or "").lower()
    return "db file exists but metadata file does not" in msg or (
        "local state is incorrect" in msg and "metadata" in msg
    )


def _backup_broken_replica_file(db_path: str) -> Optional[str]:
    """备份损坏的本地副本文件，便于后续自动重建。"""
    return _backup_broken_database_file(db_path, "检测到本地副本损坏，已备份本地副本")


def _get_cloud_lookup_replica_path(cloud_url: str) -> str:
    """为跨库云端补查生成独立副本路径，避免不同云库共享同一本地副本文件。"""
    lookup_dir = os.path.join(DATA_DIR, "profiles", ".cloud_lookup_replicas")
    os.makedirs(lookup_dir, exist_ok=True)
    fp = _hash_fingerprint((cloud_url or "").strip())
    return os.path.join(lookup_dir, f"lookup_{fp}.db")


def _get_cloud_conn(url: str, token: str, db_path: str = None, max_retries: int = 3):
    """获取 Embedded Replica 连接 (统一使用加固后的逻辑)
    
    Args:
        url: Turso 数据库 URL
        token: 认证令牌
        db_path: 本地数据库文件路径（如不提供，使用默认路径）
        max_retries: 最大重试次数
    
    Returns:
        libsql.Connection 对象（兼容 sqlite3 接口）
    """
    if not url or not token:
        raise ValueError('Turso URL and token are required')
    
    local_path = db_path or DB_PATH

    # 主库路径强制复用进程级单例写连接，避免创建第二个 sync agent
    if _is_main_db_path(local_path):
        return _get_main_write_conn_singleton(do_sync=False)

    last_error = None
    
    for attempt in range(max_retries):
        try:
            # 直接复用加固后的连接逻辑，确保 Windows 兼容性、HTTPS 强制转换
            return _connect_embedded_replica(local_path, url, token, do_sync=True)
        except Exception as e:
            last_error = e
            # 只有当检测到本地副本损坏或元数据丢失时，才执行自愈（备份并重试）
            if _is_replica_metadata_missing_error(e) or _is_sqlite_malformed_error(e):
                backup_path = _backup_broken_replica_file(local_path)
                if backup_path:
                    _debug_log(
                        f"Embedded Replica 状态损坏，已备份并尝试重建连接 (第 {attempt + 1} 次): {backup_path}",
                        level="WARNING",
                    )
                    continue
            
            # 其他错误（如认证失败、网络不通）或备份失败，则正常重试一次
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            break
            
    raise last_error or RuntimeError(f"无法建立云端连接: {url}")
def _is_cloud_connection(conn: Any) -> bool:
    """检查连接是否为 Embedded Replica 连接（而不是纯本地 SQLite）
    
    在 Embedded Replicas 模式下，cloud 连接是具有 sync() 方法的 libsql.Connection
    """
    try:
        # 检查是否有 sync() 方法（这是 Embedded Replica 连接的标志）
        return hasattr(conn, 'sync') and callable(getattr(conn, 'sync'))
    except Exception:
        return False


def _resolve_conn_context(db_path: str = None) -> Dict[str, Any]:
    """统一解析连接上下文，避免读/写连接函数重复计算。"""
    path = db_path or DB_PATH
    target_abs = os.path.abspath(path)
    main_abs = os.path.abspath(DB_PATH)
    
    # 彻底移除生产代码中的 is_test 路径判断。
    # 动态获取环境变量，确保 monkeypatch 和多用户配置生效。
    url = os.getenv('TURSO_DB_URL')
    token = os.getenv('TURSO_AUTH_TOKEN')
    hostname = os.getenv('TURSO_DB_HOSTNAME')
    
    if not url and hostname:
        url = _normalize_turso_url(hostname)

    # 检测是否为测试数据库（用于动态切换凭据）
    is_test = db_path and ("test_" in os.path.basename(db_path) or "test-" in os.path.basename(db_path))
    
    if is_test:
        url = os.getenv('TURSO_TEST_DB_URL') or url
        token = os.getenv('TURSO_TEST_AUTH_TOKEN') or token

    from config import get_force_cloud_mode
    force_cloud_mode = bool(get_force_cloud_mode())
    
    # 工业级容错处理：在启动初期（如 main.py 还没加载用户 profile 时），URL 可能为空。
    # 我们不应该在这里直接抛出 RuntimeError 导致程序无法启动，而是记录警告。
    if force_cloud_mode and not url:
        _debug_log("强制云端模式已启用，但当前环境中未发现 TURSO_DB_URL。程序将继续运行，直至真正发起连接。", level="WARNING")
    
    return {
        "db_path": path,
        "is_main_db": target_abs == main_abs,
        "is_test": is_test,
        "url": url,
        "token": token,
        "force_cloud_mode": force_cloud_mode,
    }


def _get_pooled_wrapper_if_available(db_path: str, read_only: bool) -> Optional[Any]:
    """废弃：旧连接池已替换为 ThreadLocal 读连接管理。直接返回 None。"""
    return None


def _wrap_and_track_connection(db_path: str, conn: Any, read_only: bool) -> Any:
    """直接返回连接（无需包装，ConnectionPool 已移除）。"""
    return conn


def _connect_embedded_replica(db_path: str, url: str, token: str, do_sync: bool = False) -> Any:
    """创建 Embedded Replica 连接，并按需执行首次 sync。"""
    
    # 强制将 libsql:// 转换为 https:// 以避开 Windows 特有的 WebSocket 握手 hang 机问题
    final_url = url.replace("libsql://", "https://")
    
    conn = libsql.connect(
        db_path,
        sync_url=final_url,
        auth_token=token
    )
    
    # 配置 WAL 和并发优化 PRAGMA
    try:
        conn.execute("PRAGMA busy_timeout=5000;")  # 5秒自动重试WAL锁定冲突
        conn.execute("PRAGMA synchronous=NORMAL;")  # 同步级别优化
    except Exception as e:
        _debug_log(f"Embedded Replica 配置 PRAGMA 失败（非严重）: {e}", level="WARNING")
    
    if do_sync and hasattr(conn, 'sync'):
        conn.sync()
    return conn


def _get_read_conn(db_path: str, max_retries: int = 3, retry_delay: float = 1.0, allow_local_fallback: bool = True) -> Any:
    """获取数据库连接用于读操作 - 指令 1: ThreadLocal 隔离
    
    改进：
    - 所有读操作都通过 ThreadLocal 存储获取连接
    - 每个线程仅拥有一个读连接，避免多线程竞争
    - 连接的初始化逻辑（Embedded Replicas 或本地 SQLite）保持不变
    
    Args:
        db_path: 数据库路径
        max_retries: 最大重试次数（默认 3 次，仅用于首次连接）
        retry_delay: 每次重试的延迟秒数（默认 1.0 秒）
    
    Returns:
        libsql.Connection 对象（兼容 sqlite3 接口）或 sqlite3.Connection 对象
    """
    # 指令 1: 使用 ThreadLocal 获取读连接，禁止跨线程共享
    return _get_thread_local_read_conn(db_path or DB_PATH)


def _get_read_conn_impl(db_path: str, max_retries: int = 3, retry_delay: float = 1.0, allow_local_fallback: bool = True) -> Any:
    """读连接初始化的实现细节（被 ThreadLocal 包装）。
    
    Embedded Replicas 在客户端维持本地 SQLite 副本。读操作直接从本地 SQLite 读取（无需 sync）。
    """
    ctx = _resolve_conn_context(db_path)
    db_path = ctx["db_path"]

    if _should_use_local_only_connection(db_path):
        conn = _get_local_conn(db_path)
        return _wrap_and_track_connection(db_path, conn, read_only=True)

    pooled = _get_pooled_wrapper_if_available(db_path, read_only=True)
    if pooled is not None:
        return pooled

    # 优先使用 Embedded Replicas 模式（若配置了云端凭据）
    if (ctx["is_main_db"] or ctx["is_test"]) and ctx["url"] and ctx["token"] and HAS_LIBSQL:
        last_error = None
        for attempt in range(max_retries):
            try:
                conn = _get_libsql_local_read_conn(db_path)
                return _wrap_and_track_connection(db_path, conn, read_only=True)
                
            except Exception as e:
                if _is_replica_metadata_missing_error(e) or _is_sqlite_malformed_error(e):
                    backup_path = _backup_broken_replica_file(db_path)
                    if backup_path:
                        _debug_log(
                            f"Embedded Replica 本地状态损坏，已备份并重试连接: {backup_path}",
                            level="WARNING",
                        )
                        last_error = e
                        continue
                last_error = e
                if attempt < max_retries - 1:
                    _debug_log(f"Embedded Replica 读连接失败 (尝试 {attempt + 1})，{retry_delay} 秒后重试: {e}")
                    time.sleep(retry_delay)
                else:
                    _debug_log(f"Embedded Replica 读连接失败 (已尝试 {max_retries} 次)，回退本地: {e}")

        if ctx["force_cloud_mode"]:
            raise RuntimeError(f"强制云端模式读连接失败 (已尝试 {max_retries} 次): {last_error}")

    # 无云端配置时回退本地纯 SQLite
    if allow_local_fallback and (not ctx["force_cloud_mode"] or ctx["is_test"]):
        conn = _get_local_conn(db_path)
        return _wrap_and_track_connection(db_path, conn, read_only=True)

    raise RuntimeError("强制云端模式已启用，但无法连接到云端数据库")


def _get_conn(db_path: str, max_retries: int = 3, retry_delay: float = 1.0, allow_local_fallback: bool = True, do_sync: bool = False) -> Any:
    """获取数据库连接 - Embedded Replicas 模式
    
    Embedded Replicas 在客户端维持本地 SQLite 副本，与远程 Turso 主库保持同步。
    - 读操作：直接从本地 SQLite 文件读取（微秒级延迟）
    - 写操作：自动转发到远程主库，成功后自动更新本地副本
    - 离线模式：如未配置云端凭据，退化为纯本地 SQLite

    Args:
        db_path: 数据库路径
        max_retries: 最大重试次数（默认 3 次，仅用于首次连接）
        retry_delay: 每次重试的延迟秒数（默认 1.0 秒）
    
    Returns:
        libsql.Connection 对象（兼容 sqlite3 接口）或 sqlite3.Connection 对象
    """
    ctx = _resolve_conn_context(db_path)
    db_path = ctx["db_path"]

    # 主库写连接统一走进程级单例，杜绝遗漏路径创建第二个 sync agent
    if (
        _is_main_db_path(db_path)
        and ctx.get("url")
        and ctx.get("token")
        and HAS_LIBSQL
    ):
        return _get_main_write_conn_singleton(do_sync=do_sync, max_retries=max_retries, retry_delay=retry_delay)

    if _should_use_local_only_connection(db_path):
        _debug_log(f"使用本地 SQLite 模式: {db_path}")
        conn = _get_local_conn(db_path)
        return _wrap_and_track_connection(db_path, conn, read_only=False)

    pooled = _get_pooled_wrapper_if_available(db_path, read_only=False)
    if pooled is not None:
        return pooled

    # 优先使用 Embedded Replicas 模式（若配置了云端凭据）
    if (ctx["is_main_db"] or ctx["is_test"]) and ctx["url"] and ctx["token"] and HAS_LIBSQL:
        last_error = None
        for attempt in range(max_retries):
            try:
                _debug_log_throttled(
                    key=f"libsql-connect-attempt:{'test' if ctx['is_test'] else 'main'}",
                    msg=f"Embedded Replicas 首次连接 (第 {attempt + 1}/{max_retries} 次)",
                    interval_seconds=30.0,
                )
                
                # ✅ 创建 Embedded Replica 连接
                conn = _connect_embedded_replica(db_path, ctx["url"], ctx["token"], do_sync=do_sync)
                
                # 首次连接时立即同步一次，确保本地数据最新
                if hasattr(conn, 'sync'):
                    _debug_log(f"Embedded Replica 连接完成并同步: {db_path} ↔ {ctx['url'][:50]}...")
                
                return _wrap_and_track_connection(db_path, conn, read_only=False)
                
            except Exception as e:
                if _is_replica_metadata_missing_error(e) or _is_sqlite_malformed_error(e):
                    backup_path = _backup_broken_replica_file(db_path)
                    if backup_path:
                        _debug_log(
                            f"Embedded Replica 本地状态损坏，已备份并重试连接: {backup_path}",
                            level="WARNING",
                        )
                        last_error = e
                        continue
                last_error = e
                if attempt < max_retries - 1:
                    _debug_log(f"Embedded Replica 连接失败 (尝试 {attempt + 1})，{retry_delay} 秒后重试: {e}")
                    time.sleep(retry_delay)
                else:
                    _debug_log(f"Embedded Replica 连接失败 (已尝试 {max_retries} 次)，回退本地: {e}")

        # 若主配置连接失败，尝试通过 Turso 管理 API 发现当前用户目标库并重连
        if not ctx["is_test"]:
            try:
                preferred_db_name = f"history-{(ACTIVE_USER or '').lower()}"
                for candidate_url, candidate_token, source_label in _get_cached_turso_cloud_targets():
                    if preferred_db_name not in source_label:
                        continue
                    _debug_log(f"尝试 API 发现的用户库连接: {source_label}")
                    try:
                        conn = _connect_embedded_replica(db_path, candidate_url, candidate_token, do_sync=True)
                        return _wrap_and_track_connection(db_path, conn, read_only=False)
                    except Exception as fallback_error:
                        _debug_log(f"API 发现的库连接失败: {fallback_error}")
                        continue
            except Exception as api_error:
                _debug_log(f"API 发现用户库过程失败: {api_error}")

        if ctx["force_cloud_mode"]:
            raise RuntimeError(f"强制云端模式连接失败 (已尝试 {max_retries} 次): {last_error}")

    # 无云端配置时回退本地纯 SQLite
    if allow_local_fallback and (not ctx["force_cloud_mode"] or ctx["is_test"]):
        _debug_log(f"使用本地 SQLite 模式: {db_path}")
        conn = _get_local_conn(db_path)
        return _wrap_and_track_connection(db_path, conn, read_only=False)

    raise RuntimeError("强制云端模式已启用，但无法连接到云端数据库")


def _create_tables(cur, skip_migrations=False):
    """
    创建数据库表结构

    Args:
        cur: 数据库游标
        skip_migrations: 是否跳过迁移操作（列添加、数据更新）
                        用于云端数据库初始化，避免重复执行耗时操作
    """
    # 创建表（如果不存在）
    cur.execute('CREATE TABLE IF NOT EXISTS processed_words (voc_id TEXT PRIMARY KEY, spelling TEXT, processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cur.execute('CREATE TABLE IF NOT EXISTS ai_word_notes (voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT, ielts_focus TEXT, collocations TEXT, traps TEXT, synonyms TEXT, discrimination TEXT, example_sentences TEXT, memory_aid TEXT, word_ratings TEXT, raw_full_text TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, batch_id TEXT, original_meanings TEXT, maimemo_context TEXT, content_origin TEXT, content_source_db TEXT, content_source_scope TEXT, it_level INTEGER DEFAULT 0, it_history TEXT, sync_status INTEGER DEFAULT 0, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cur.execute('CREATE TABLE IF NOT EXISTS ai_word_iterations (id INTEGER PRIMARY KEY AUTOINCREMENT, voc_id TEXT NOT NULL, spelling TEXT, stage TEXT, it_level INTEGER, score REAL, justification TEXT, tags TEXT, refined_content TEXT, candidate_notes TEXT, raw_response TEXT, maimemo_context TEXT, batch_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(voc_id) REFERENCES ai_word_notes(voc_id))')
    cur.execute('CREATE TABLE IF NOT EXISTS word_progress_history (id INTEGER PRIMARY KEY AUTOINCREMENT, voc_id TEXT, familiarity_short REAL, familiarity_long REAL, review_count INTEGER, it_level INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    # 添加联合唯一约束，避免历史记录冗余同步
    try: cur.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_progress_unique ON word_progress_history (voc_id, created_at, review_count)')
    except: pass
    cur.execute('CREATE TABLE IF NOT EXISTS ai_batches (batch_id TEXT PRIMARY KEY, request_id TEXT, ai_provider TEXT, model_name TEXT, prompt_version TEXT, batch_size INTEGER, total_latency_ms INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, finish_reason TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cur.execute('CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cur.execute('CREATE TABLE IF NOT EXISTS test_run_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, total_count INTEGER, sample_count INTEGER, sample_words TEXT, ai_calls INTEGER, success_parsed INTEGER, is_dry_run BOOLEAN, error_msg TEXT, ai_results_json TEXT)')

    # 添加缺失的列（云端也需要，避免旧库缺少新字段）
    for t, c, d in [
        ('ai_word_notes', 'it_level',          'INTEGER DEFAULT 0'),
        ('ai_word_notes', 'it_history',         'TEXT'),
        ('ai_word_notes', 'prompt_tokens',      'INTEGER DEFAULT 0'),
        ('ai_word_notes', 'completion_tokens',  'INTEGER DEFAULT 0'),
        ('ai_word_notes', 'total_tokens',       'INTEGER DEFAULT 0'),
        ('ai_word_notes', 'batch_id',           'TEXT'),
        ('ai_word_notes', 'original_meanings',  'TEXT'),
        ('ai_word_notes', 'maimemo_context',    'TEXT'),
        ('ai_word_notes', 'content_origin',     'TEXT'),
        ('ai_word_notes', 'content_source_db',  'TEXT'),
        ('ai_word_notes', 'content_source_scope','TEXT'),
        ('ai_word_notes', 'raw_full_text',      'TEXT'),
        ('ai_word_notes', 'word_ratings',       'TEXT'),
        ('ai_word_notes', 'sync_status',        'INTEGER DEFAULT 0'),
        ('ai_word_notes', 'updated_at',         'TIMESTAMP'),
        ('processed_words', 'updated_at',      'TIMESTAMP'),
    ]:
        try:
            cur.execute(f'ALTER TABLE {t} ADD COLUMN {c} {d}')
            _debug_log(f"  列添加成功: {t}.{c}")
        except Exception as e:
            if "duplicate column name" not in str(e).lower():
                _debug_log(f"  列添加失败: {t}.{c} -> {e}")

    try:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS ai_word_iterations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voc_id TEXT NOT NULL,
                spelling TEXT,
                stage TEXT,
                it_level INTEGER,
                score REAL,
                justification TEXT,
                tags TEXT,
                refined_content TEXT,
                candidate_notes TEXT,
                raw_response TEXT,
                maimemo_context TEXT,
                batch_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(voc_id) REFERENCES ai_word_notes(voc_id)
            )
        ''')
    except Exception as e:
        _debug_log(f"  ai_word_iterations 创建/校验失败: {e}")

    # 跳过旧数据回填操作（用于云端数据库初始化）
    if skip_migrations:
        return

    # 手动为旧数据补齐时间戳，确保同步逻辑能正常运行
    try:
        cur.execute("UPDATE ai_word_notes SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
        cur.execute("UPDATE processed_words SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")

        # 为历史笔记补齐来源字段：
        # - 有 batch_id 的旧记录，默认视为历史 AI 生成
        # - 没有任何来源线索的旧记录，标记为 legacy_unknown
        cur.execute("UPDATE ai_word_notes SET content_origin = 'ai_generated', content_source_scope = 'ai_batch' WHERE content_origin IS NULL AND batch_id IS NOT NULL")
        cur.execute("UPDATE ai_word_notes SET content_origin = 'legacy_unknown', content_source_scope = 'legacy' WHERE content_origin IS NULL AND batch_id IS NULL")
    except: pass

@log_performance(lambda: ContextLogger(logging.getLogger(__name__)))
def init_concurrent_system():
    """初始化高并发系统组件（程序启动时调用）。
    
    - 启动后台写守护线程
    - 启动后台同步守护线程
    - 准备 ThreadLocal 读连接存储
    """
    _start_writer_daemon()
    _start_sync_daemon()
    _debug_log("并发系统初始化完成", level="INFO")


def cleanup_concurrent_system():
    """清理高并发系统组件（程序退出时调用）。
    
    - 停止后台写守护线程
    - 停止后台同步守护线程
    - 清理 ThreadLocal 读连接
    """
    _stop_writer_daemon(timeout_seconds=5.0)
    _stop_sync_daemon(timeout_seconds=2.0)
    _cleanup_thread_local_read_conns()
    _close_main_write_conn_singleton()
    _close_hub_write_conn_singleton()
    _debug_log("并发系统清理完成", level="INFO")


def init_db(db_path: str = None):
    """初始化数据库，确保本地和云端 schema 一致。"""
    path = db_path or DB_PATH
    start_time = time.time()
    
    is_test = 'test_' in os.path.basename(path)
    is_main_db = _is_main_db_path(path)
    url = TURSO_TEST_DB_URL if is_test else TURSO_DB_URL
    token = TURSO_TEST_AUTH_TOKEN if is_test else TURSO_AUTH_TOKEN
    
    if not url:
        hostname = TURSO_TEST_DB_HOSTNAME if is_test else TURSO_DB_HOSTNAME
        if hostname:
            url = _normalize_turso_url(hostname)
            
    is_cloud_configured = bool(HAS_LIBSQL and url and token)

    if is_cloud_configured:
        # 云端同步模式：绝对不能直接用 pure sqlite3 (如 _get_local_conn) 创建文件，
        # 否则会导致 libsql metadata 缺失报错 (local state is incorrect)
        try:
            main_fp = _main_db_fingerprint(path)
            # 检查是否已经初始化过（通过本地标记文件）
            if _is_db_initialized("main", main_fp):
                _debug_log("云端数据库已初始化（通过标记文件），跳过检查")
            else:
                cloud_start = time.time()
                if is_main_db:
                    cc = _get_main_write_conn_singleton(do_sync=False)
                else:
                    cc = _get_cloud_conn(url, token, db_path=path)
                _debug_log("云端数据库连接完成", cloud_start)

                ccur = cc.cursor()
                check_start = time.time()
                table_exists = _check_table_exists(ccur, "processed_words", "main", cache_scope=main_fp)
                _debug_log(f"表存在检查完成 (存在: {table_exists})", check_start)

                create_start = time.time()
                # 即使主表已存在，也要执行 schema 校验/补齐，避免新增列缺失（如 content_origin）。
                with _main_write_conn_op_lock:
                    _create_tables(ccur, skip_migrations=True)
                    if table_exists:
                        _debug_log("云端数据库 schema 校验与补齐完成（跳过数据回填）", create_start)
                    else:
                        _debug_log("云端数据库存储初始化完成（跳过迁移）", create_start)

                # 标记数据库已初始化
                _mark_db_initialized("main", main_fp)
                with _main_write_conn_op_lock:
                    cc.commit()
        except Exception as e:
            _debug_log(f"云端数据库初始化失败 (可能网络不通或凭据过期): {e}", start_time)
    else:
        # 纯本地模式
        try:
            lc = _get_local_conn(path)
            lcur = lc.cursor()
            _create_tables(lcur)
            lc.commit()
            lc.close()
            _debug_log("本地数据库初始化/迁移完成", start_time)
        except Exception as e:
            _debug_log(f"本地数据库初始化失败: {e}", start_time)

    # 3. 确保 Hub 数据库表结构完整
    hub_start = time.time()
    hub_ok = init_users_hub_tables()
    if hub_ok:
        _debug_log("Hub 数据库初始化完成", hub_start)
    else:
        _debug_log("Hub 数据库初始化失败（已记录原因）", hub_start, level="WARNING")

@log_performance(lambda: ContextLogger(logging.getLogger(__name__)))
def get_processed_ids_in_batch(voc_ids: list, db_path: str = None) -> set:
    if not voc_ids:
        return set()

    try:
        s = time.time()
        c = _get_read_conn(db_path or DB_PATH)
        cur = c.cursor()
        vs = [str(v) for v in voc_ids]
        ph = ','.join(['?'] * len(vs))
        cur.execute(f'SELECT voc_id FROM processed_words WHERE voc_id IN ({ph})', vs)
        res = {str(r[0] if isinstance(r, (tuple,list)) else r['voc_id']) for r in cur.fetchall()}
        c.close()
        _debug_log(f'批量查询 ({len(voc_ids)} 词)', s)
        return res
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            _debug_log_throttled(
                "get_processed_ids_batch_corruption",
                f"get_processed_ids_in_batch 数据损坏异常: {e}",
                level="WARNING"
            )
            return set()
        _debug_log(f"get_processed_ids_in_batch 异常: {e}", level="WARNING")
        return set()


def get_progress_tracked_ids_in_batch(voc_ids: list, db_path: str = None) -> set:
    """批量查询在 word_progress_history 中有学习记录的 voc_id。"""
    if not voc_ids:
        return set()

    try:
        c = _get_read_conn(db_path or DB_PATH)
        cur = c.cursor()
        vs = [str(v) for v in voc_ids]
        ph = ','.join(['?'] * len(vs))
        cur.execute(f'SELECT DISTINCT voc_id FROM word_progress_history WHERE voc_id IN ({ph})', vs)
        res = {str(r[0] if isinstance(r, (tuple, list)) else r['voc_id']) for r in cur.fetchall()}
        c.close()
        return res
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            _debug_log_throttled(
                "get_progress_tracked_ids_batch_corruption",
                f"get_progress_tracked_ids_in_batch 数据损坏异常: {e}",
                level="WARNING"
            )
            return set()
        _debug_log(f"get_progress_tracked_ids_in_batch 异常: {e}", level="WARNING")
        return set()

def is_processed(voc_id: str, db_path: str = None) -> bool:
    try:
        c = _get_read_conn(db_path or DB_PATH)
        cur = c.cursor()
        cur.execute('SELECT 1 FROM processed_words WHERE voc_id = ?', (str(voc_id),))
        res = cur.fetchone() is not None
        c.close()
        return res
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            _debug_log_throttled(
                "is_processed_corruption",
                f"is_processed 数据损坏异常: {e}",
                level="WARNING"
            )
            return False
        _debug_log(f"is_processed 异常: {e}", level="WARNING")
        return False


def _run_with_managed_connection(
    optional_conn: Any,
    conn_factory: Callable[[], Any],
    operation: Callable[[Any], Any],
) -> Any:
    """统一处理可复用连接：外部连接不提交不关闭，自建连接自动提交并关闭。"""
    owned = optional_conn is None
    target_conn = optional_conn or conn_factory()
    conn_lock = _get_singleton_conn_op_lock(target_conn)
    try:
        if conn_lock is not None:
            with conn_lock:
                result = operation(target_conn)
                if owned:
                    target_conn.commit()
        else:
            result = operation(target_conn)
            if owned:
                target_conn.commit()
        return result
    finally:
        if owned:
            try:
                if not _is_main_write_singleton_conn(target_conn) and not _is_hub_write_singleton_conn(target_conn):
                    target_conn.close()
            except Exception:
                pass


def _should_use_local_only_connection(db_path: str = None, conn: Any = None) -> bool:
    """显式提供独立数据库连接/路径时，优先走本地直写/直读。"""
    if conn is not None:
        return True
    if db_path is None:
        db_path = DB_PATH

    if os.path.abspath(db_path) != os.path.abspath(DB_PATH):
        return True

    ctx = _resolve_conn_context(db_path)
    return not (ctx.get("url") and ctx.get("token") and HAS_LIBSQL)


def _execute_write_sql_sync(sql: str, params: tuple = (), db_path: str = None, conn: Any = None) -> None:
    """同步执行单条写 SQL。"""
    owned = conn is None
    target_conn = conn or _get_local_conn(db_path or DB_PATH)
    try:
        cur = target_conn.cursor()
        cur.execute(sql, params)
        if owned:
            target_conn.commit()
        else:
            target_conn.commit()
        _mark_main_db_needs_sync(db_path=db_path, conn=target_conn)
    finally:
        if owned:
            try:
                target_conn.close()
            except Exception:
                pass


def _execute_batch_write_sql_sync(sql: str, args_list: List[Tuple], db_path: str = None, conn: Any = None) -> None:
    """同步执行批量写 SQL。"""
    if not args_list:
        return

    owned = conn is None
    target_conn = conn or _get_local_conn(db_path or DB_PATH)
    try:
        cur = target_conn.cursor()
        cur.executemany(sql, args_list)
        if owned:
            target_conn.commit()
        else:
            target_conn.commit()
        _mark_main_db_needs_sync(db_path=db_path, conn=target_conn)
    finally:
        if owned:
            try:
                target_conn.close()
            except Exception:
                pass

def mark_processed(voc_id: str, spelling: str, db_path: str = None, conn: Any = None):
    """支持连接复用的标记处理函数
    
    使用 Embedded Replicas 连接时，一次写入自动同步本地+云端，无需显式双写。
    """
    try:
        sql = 'INSERT OR REPLACE INTO processed_words (voc_id, spelling, updated_at) VALUES (?, ?, ?)'
        args = (str(voc_id), spelling, get_timestamp_with_tz())
        if _should_use_local_only_connection(db_path, conn):
            _execute_write_sql_sync(sql, args, db_path=db_path, conn=conn)
            return True
        if not _queue_write_operation(sql, args, op_type="insert_or_replace"):
            _debug_log("mark_processed 入队失败: 写队列已满", level="WARNING")
            return False
        return True
    except Exception as e:
        _debug_log(f"mark_processed 写入失败: {e}")
        return False


def mark_processed_batch(items: List[Tuple[str, str]], db_path: str = None) -> bool:
    """批量标记 processed_words（异步入队 executemany）。"""
    if not items:
        return True

    try:
        sql = 'INSERT OR REPLACE INTO processed_words (voc_id, spelling, updated_at) VALUES (?, ?, ?)'
        ts = get_timestamp_with_tz()
        args_list = [(str(voc_id), spelling, ts) for voc_id, spelling in items]
        if _should_use_local_only_connection(db_path):
            _execute_batch_write_sql_sync(sql, args_list, db_path=db_path)
            return True
        if not _queue_batch_write_operation(sql, args_list):
            _debug_log("mark_processed_batch 入队失败: 写队列已满", level="WARNING")
            return False
        return True
    except Exception as e:
        _debug_log(f"mark_processed_batch 失败: {e}", level="WARNING")
        return False

def log_progress_snapshots(words: List[dict], db_path: str = None):
    if not words:
        return 0

    s_all = time.time()
    c = _get_read_conn(db_path or DB_PATH)
    cur = c.cursor()
    vids = [str(w['voc_id']) for w in words]
    ph = ','.join(['?'] * len(vids))
    cur.execute(f'SELECT voc_id, it_level FROM ai_word_notes WHERE voc_id IN ({ph})', vids)
    itm = {str(r[0]): r[1] for r in cur.fetchall()}
    cur.execute(f'SELECT voc_id, familiarity_short, review_count FROM word_progress_history WHERE voc_id IN ({ph}) ORDER BY created_at DESC', vids)
    lh = {}
    for r in cur.fetchall():
        v = str(r[0])
        if v not in lh:
            lh[v] = (r[1], r[2])

    ins = []
    for w in words:
        v = str(w['voc_id'])
        nf = w.get('short_term_familiarity', 0) or w.get('voc_familiarity', 0)
        nr = w.get('review_count', 0)
        l = lh.get(v)
        if not l or abs(l[0] - float(nf)) > 0.01 or l[1] != int(nr):
            ins.append((v, nf, w.get('long_term_familiarity', 0), nr, itm.get(v, 0)))

    if ins:
        sql = 'INSERT INTO word_progress_history (voc_id, familiarity_short, familiarity_long, review_count, it_level) VALUES (?, ?, ?, ?, ?)'
        if _should_use_local_only_connection(db_path):
            _execute_batch_write_sql_sync(sql, ins, db_path=db_path)
            c.close()
            _debug_log(f'进度同步 ({len(ins)} 条)', s_all)
            return len(ins)
        if not _queue_batch_write_operation(sql, ins):
            _debug_log("log_progress_snapshots 入队失败: 写队列已满", level="WARNING")
            c.close()
            return 0

    c.close()
    _debug_log(f'进度同步 ({len(ins)} 条)', s_all)
    return len(ins)


def _clean_payload_field(payload: Dict[str, Any], field: str) -> str:
    """从 payload 读取字段并做墨墨清洗。"""
    return clean_for_maimemo(payload.get(field, ''))

@log_performance(lambda: ContextLogger(logging.getLogger(__name__)))
def save_ai_word_note(voc_id: str, payload: dict, db_path: str = None, metadata: dict = None, conn: Any = None):
    """支持连接复用的笔记保存函数
    
    使用 Embedded Replicas 连接时，一次写入自动同步本地+云端，无需显式双写。
    """
    s = payload.get('spelling', '')
    _raw_candidate = {k: v for k, v in payload.items() if k != 'raw_full_text'}
    t = payload.get('raw_full_text') or json.dumps(_raw_candidate, ensure_ascii=False)
    m_ctx = json.dumps(metadata.get('maimemo_context', {}), ensure_ascii=False) if metadata and metadata.get('maimemo_context') else None
    original_meanings = metadata.get('original_meanings') if metadata else None
    if not original_meanings:
        original_meanings = payload.get('original_meanings')
    content_origin = (metadata.get('content_origin') if metadata else None) or payload.get('content_origin') or 'ai_generated'
    content_source_db = (metadata.get('content_source_db') if metadata else None) or payload.get('content_source_db')
    content_source_scope = (metadata.get('content_source_scope') if metadata else None) or payload.get('content_source_scope')
    args = (
        str(voc_id), s,
        _clean_payload_field(payload, 'basic_meanings'),
        _clean_payload_field(payload, 'ielts_focus'),
        _clean_payload_field(payload, 'collocations'),
        _clean_payload_field(payload, 'traps'),
        _clean_payload_field(payload, 'synonyms'),
        _clean_payload_field(payload, 'discrimination'),
        _clean_payload_field(payload, 'example_sentences'),
        _clean_payload_field(payload, 'memory_aid'),
        _clean_payload_field(payload, 'word_ratings'),
        t,
        payload.get('prompt_tokens', 0),
        payload.get('completion_tokens', 0),
        payload.get('total_tokens', 0),
        metadata.get('batch_id') if metadata else None,
        original_meanings,
        m_ctx,
        content_origin,
        content_source_db,
        content_source_scope,
        0,
        get_timestamp_with_tz(),
    )
    sql = 'INSERT OR REPLACE INTO ai_word_notes (voc_id, spelling, basic_meanings, ielts_focus, collocations, traps, synonyms, discrimination, example_sentences, memory_aid, word_ratings, raw_full_text, prompt_tokens, completion_tokens, total_tokens, batch_id, original_meanings, maimemo_context, content_origin, content_source_db, content_source_scope, sync_status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'

    # 指令 2：改用异步队列提交，避免高并发线程直接竞争写连接
    try:
        if _should_use_local_only_connection(db_path, conn):
            _execute_write_sql_sync(sql, args, db_path=db_path, conn=conn)
            return True
        _queue_write_operation(sql, args, op_type="insert_or_replace")
        return True
    except Exception as e:
        _debug_log(f"save_ai_word_note 入队失败: {e}", level="ERROR")
        return False


def save_ai_word_notes_batch(notes_data: List[Dict[str, Any]], db_path: str = None, conn: Any = None) -> bool:
    """批量保存 AI 笔记到本地数据库（后台同步到云端）

    Args:
        notes_data: 笔记数据列表，每个元素包含 voc_id, payload, metadata
        db_path: 数据库路径
        conn: 可选的数据库连接（用于复用连接）

    Returns:
        是否保存成功
    """
    if not notes_data:
        return True

    try:
        sql = 'INSERT OR REPLACE INTO ai_word_notes (voc_id, spelling, basic_meanings, ielts_focus, collocations, traps, synonyms, discrimination, example_sentences, memory_aid, word_ratings, raw_full_text, prompt_tokens, completion_tokens, total_tokens, batch_id, original_meanings, maimemo_context, content_origin, content_source_db, content_source_scope, sync_status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'

        batch_args = []
        for data in notes_data:
            voc_id = data.get('voc_id')
            payload = data.get('payload', {})
            metadata = data.get('metadata', {})

            s = payload.get('spelling', '')
            _raw_candidate = {k: v for k, v in payload.items() if k != 'raw_full_text'}
            t = payload.get('raw_full_text') or json.dumps(_raw_candidate, ensure_ascii=False)
            m_ctx = json.dumps(metadata.get('maimemo_context', {}), ensure_ascii=False) if metadata and metadata.get('maimemo_context') else None

            original_meanings = metadata.get('original_meanings') if metadata else None
            if not original_meanings:
                original_meanings = payload.get('original_meanings')
            content_origin = (metadata.get('content_origin') if metadata else None) or payload.get('content_origin') or 'ai_generated'
            content_source_db = (metadata.get('content_source_db') if metadata else None) or payload.get('content_source_db')
            content_source_scope = (metadata.get('content_source_scope') if metadata else None) or payload.get('content_source_scope')
            
            # 根据 content_origin 决定初始同步状态
            # - ai_generated: 需要同步 (sync_status=0)
            # - 其他: 已从云端/历史查到，无须当前用户同步 (sync_status=1)
            if content_origin == 'ai_generated':
                initial_sync_status = 0
            elif content_origin in ('community_reused', 'current_db_reused', 'history_reused'):
                initial_sync_status = 1  # 这些内容已在云端，标记为已同步
            else:
                # legacy_unknown 或其他未知来源，保守处理为待同步
                initial_sync_status = 0
            
            args = (
                str(voc_id), s,
                _clean_payload_field(payload, 'basic_meanings'),
                _clean_payload_field(payload, 'ielts_focus'),
                _clean_payload_field(payload, 'collocations'),
                _clean_payload_field(payload, 'traps'),
                _clean_payload_field(payload, 'synonyms'),
                _clean_payload_field(payload, 'discrimination'),
                _clean_payload_field(payload, 'example_sentences'),
                _clean_payload_field(payload, 'memory_aid'),
                _clean_payload_field(payload, 'word_ratings'),
                t,
                payload.get('prompt_tokens', 0),
                payload.get('completion_tokens', 0),
                payload.get('total_tokens', 0),
                metadata.get('batch_id') if metadata else None,
                original_meanings,
                m_ctx,
                content_origin,
                content_source_db,
                content_source_scope,
                initial_sync_status,
                get_timestamp_with_tz(),
            )
            batch_args.append(args)

        if _should_use_local_only_connection(db_path, conn):
            _execute_batch_write_sql_sync(sql, batch_args, db_path=db_path, conn=conn)
        elif not _queue_batch_write_operation(sql, batch_args):
            _debug_log("批量保存 AI 笔记入队失败: 写队列已满", level="WARNING")
            return False

        _debug_log(f"批量保存 AI 笔记完成：{len(notes_data)} 个单词（本地数据库）")
        return True

    except Exception as e:
        _debug_log(f"批量保存 AI 笔记失败: {e}")
        return False

def save_ai_word_iteration(voc_id: str, payload: dict, db_path: str = None, metadata: dict = None, conn: Any = None) -> bool:
    """保存单次迭代结果到独立历史表
    
    使用 Embedded Replicas 连接时，一次写入自动同步本地+云端，无需显式双写。
    """
    if not voc_id:
        return False

    try:
        data = payload or {}
        meta = metadata or {}
        batch_id = meta.get('batch_id')
        m_ctx = json.dumps(meta.get('maimemo_context', {}), ensure_ascii=False) if meta.get('maimemo_context') else None
        tags = data.get('tags')
        tags_json = json.dumps(tags, ensure_ascii=False) if tags is not None else None
        raw_response = data.get('raw_response') or data.get('raw_full_text') or json.dumps(data, ensure_ascii=False)

        args = (
            str(voc_id),
            data.get('spelling'),
            data.get('stage'),
            data.get('it_level'),
            data.get('score'),
            data.get('justification'),
            tags_json,
            data.get('refined_content'),
            data.get('candidate_notes'),
            raw_response,
            m_ctx,
            batch_id,
        )

        sql = '''
            INSERT INTO ai_word_iterations (
                voc_id, spelling, stage, it_level, score, justification, tags,
                refined_content, candidate_notes, raw_response, maimemo_context, batch_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''

        if _should_use_local_only_connection(db_path, conn):
            _execute_write_sql_sync(sql, args, db_path=db_path, conn=conn)
            return True
        if not _queue_write_operation(sql, args, op_type="insert_or_replace"):
            _debug_log("save_ai_word_iteration 入队失败: 写队列已满", level="WARNING")
            return False

        return True
    except Exception as e:
        _debug_log(f"保存迭代历史失败: {e}")
        return False


def update_ai_word_note_iteration_state(
    voc_id: str,
    level: int,
    it_history_json: str,
    memory_aid: Optional[str] = None,
    db_path: str = None,
) -> bool:
    """异步更新 ai_word_notes 的迭代字段（it_level/it_history/updated_at[/memory_aid]）。"""
    try:
        if memory_aid is not None:
            sql = (
                "UPDATE ai_word_notes "
                "SET it_level = ?, it_history = ?, memory_aid = ?, updated_at = ? "
                "WHERE voc_id = ?"
            )
            args = (
                int(level),
                it_history_json,
                memory_aid,
                get_timestamp_with_tz(),
                str(voc_id),
            )
        else:
            sql = (
                "UPDATE ai_word_notes "
                "SET it_level = ?, it_history = ?, updated_at = ? "
                "WHERE voc_id = ?"
            )
            args = (
                int(level),
                it_history_json,
                get_timestamp_with_tz(),
                str(voc_id),
            )

        if _should_use_local_only_connection(db_path):
            _execute_write_sql_sync(sql, args, db_path=db_path)
            return True
        if not _queue_write_operation(sql, args, op_type="insert_or_replace"):
            _debug_log("update_ai_word_note_iteration_state 入队失败: 写队列已满", level="WARNING")
            return False
        return True
    except Exception as e:
        _debug_log(f"update_ai_word_note_iteration_state 失败: {e}", level="WARNING")
        return False

def set_note_sync_status(voc_id: str, sync_status: int, db_path: str = None) -> bool:
    """更新指定单词笔记的同步状态
    
    使用 Embedded Replicas 连接时，一次写入自动同步本地+云端，无需显式双写。

    sync_status 约定：
    - 0: 云端未检出自己的释义
    - 1: 云端释义与数据库内容一致
    - 2: 云端已存在自己的释义，但内容与数据库不一致
    """
    def _status_text(value: int) -> str:
        mapping = {
            0: "待同步（未检出墨墨已创建释义）",
            1: "已同步（墨墨已创建释义与本地一致）",
            2: "冲突（墨墨已创建释义与本地不一致）",
        }
        return mapping.get(int(value), "未知状态")

    target_status = int(sync_status)
    target_status_text = _status_text(target_status)

    try:
        sql = 'UPDATE ai_word_notes SET sync_status = ?, updated_at = ? WHERE voc_id = ?'
        args = (target_status, get_timestamp_with_tz(), str(voc_id))
        if _should_use_local_only_connection(db_path):
            _execute_write_sql_sync(sql, args, db_path=db_path)
            _debug_log(
                f"写入已同步: sync_status={target_status}（{target_status_text}）"
            )
            return True
        if not _queue_write_operation(sql, args, op_type="insert_or_replace"):
            _debug_log(
                f"写入入队失败: voc_id={voc_id}, 目标sync_status={target_status}（{target_status_text}）",
                level="WARNING",
            )
            return False

        _debug_log(
            f"写入已入队: sync_status={target_status}（{target_status_text}）"
        )
        return True

    except Exception as e:
        _debug_log(
            f"写入失败: voc_id={voc_id}, 目标sync_status={target_status}（{target_status_text}）, error={e}"
        )
        return False


def mark_note_synced(voc_id: str, db_path: str = None) -> bool:
    """标记指定单词笔记为已同步（sync_status = 1）"""
    return set_note_sync_status(voc_id, 1, db_path=db_path)


def mark_note_sync_conflict(voc_id: str, db_path: str = None) -> bool:
    """标记指定单词笔记为冲突状态（sync_status = 2）"""
    return set_note_sync_status(voc_id, 2, db_path=db_path)

def get_unsynced_notes(db_path: str = None, _recovery_attempted: bool = False) -> list:
    """获取所有未同步的笔记（sync_status = 0 AND content_origin = 'ai_generated'）。"""
    unsynced_sql = '''SELECT voc_id, spelling, basic_meanings, ielts_focus, collocations,
                      traps, synonyms, discrimination, example_sentences, memory_aid,
                      word_ratings, raw_full_text, batch_id, original_meanings,
                      maimemo_context, it_level, updated_at, content_origin
               FROM ai_word_notes
               WHERE sync_status = 0
                 AND (content_origin IS NULL OR content_origin = 'ai_generated')
               ORDER BY updated_at ASC'''

    try:
        path = db_path or DB_PATH
        conn = _get_read_conn(path)
        cur = conn.cursor()
        cur.execute(unsynced_sql)
        rows = cur.fetchall()
        conn.close()
        result = [_row_to_dict(cur, row) for row in rows]
        _debug_log(f"获取未同步笔记完成: {len(result)} 条 (仅 ai_generated)")
        return result
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            path = db_path or DB_PATH

            if not _recovery_attempted:
                _release_db_file_handles_for_recovery(path)
                backup_path = _backup_broken_database_file(path, "检测到本地数据库损坏，已备份本地数据库")
                if not backup_path:
                    _debug_log(
                        "损坏库备份未完成（源文件可能被占用），继续尝试云端/本地重建",
                        level="WARNING",
                    )

                try:
                    ctx = _resolve_conn_context(path)
                    if HAS_LIBSQL and ctx.get("url") and ctx.get("token"):
                        repair_conn = _get_conn(path, allow_local_fallback=False, do_sync=True)
                        try:
                            repair_conn.close()
                        except Exception:
                            pass
                        _debug_log(
                            f"获取未同步笔记命中损坏，已通过云端副本重建本地数据库: {path}",
                            level="WARNING",
                        )
                        return get_unsynced_notes(path, _recovery_attempted=True)

                    local_conn = _get_local_conn(path)
                    try:
                        _create_tables(local_conn.cursor())
                        local_conn.commit()
                    finally:
                        try:
                            local_conn.close()
                        except Exception:
                            pass
                    _debug_log(
                        f"获取未同步笔记命中损坏，未启用云端重建，已初始化本地空库: {path}",
                        level="WARNING",
                    )
                    return get_unsynced_notes(path, _recovery_attempted=True)
                except Exception as recovery_error:
                    _debug_log(
                        f"获取未同步笔记自动恢复失败: {recovery_error}",
                        level="WARNING",
                    )

            if _recovery_attempted:
                try:
                    ctx = _resolve_conn_context(path)
                    if HAS_LIBSQL and ctx.get("url") and ctx.get("token"):
                        recovery_dir = os.path.join(DATA_DIR, "profiles", ".recovery_replicas")
                        os.makedirs(recovery_dir, exist_ok=True)
                        recovery_fp = _hash_fingerprint((ctx.get("url") or "").strip())
                        recovery_path = os.path.join(recovery_dir, f"unsynced_{recovery_fp}_{int(time.time())}.db")
                        cloud_conn = _get_cloud_conn(ctx["url"], ctx["token"], db_path=recovery_path, max_retries=1)
                        cloud_cur = cloud_conn.cursor()
                        cloud_cur.execute(unsynced_sql)
                        cloud_rows = cloud_cur.fetchall()
                        cloud_conn.close()
                        cloud_result = [_row_to_dict(cloud_cur, row) for row in cloud_rows]
                        _debug_log(
                            f"本地损坏恢复未生效，已改用独立云端副本读取未同步队列: {len(cloud_result)} 条",
                            level="WARNING",
                        )
                        return cloud_result
                except Exception as cloud_fallback_error:
                    _debug_log(
                        f"独立云端副本兜底读取未同步队列失败: {cloud_fallback_error}",
                        level="WARNING",
                    )

            _debug_log_throttled(
                "get_unsynced_notes_corruption",
                f"获取未同步笔记失败（本地数据损坏）: {e}，返回空列表",
                level="WARNING"
            )
            return []
        _debug_log(f"获取未同步笔记异常: {e}", level="WARNING")
        return []

def get_word_note(voc_id: str, db_path: str = None) -> Optional[dict]:
    target_path = db_path or DB_PATH
    c = _get_read_conn(target_path)
    try:
        cur = c.cursor()
        cur.execute('SELECT * FROM ai_word_notes WHERE voc_id = ?', (str(voc_id),))
        r = cur.fetchone()
        return _row_to_dict(cur, r) if r else None
    except Exception as read_error:
        if not _is_sqlite_data_corruption_error(read_error):
            raise

        _debug_log_throttled(
            key=f"word-note-read-corruption:{os.path.abspath(target_path)}",
            msg=f"检测到读路径数据异常，尝试云端主连接兜底读取: {read_error}",
            interval_seconds=15.0,
            level="WARNING",
        )

        try:
            fallback_conn = _get_read_conn(target_path, allow_local_fallback=False)
            fallback_cur = fallback_conn.cursor()
            fallback_cur.execute('SELECT * FROM ai_word_notes WHERE voc_id = ?', (str(voc_id),))
            fallback_row = fallback_cur.fetchone()
            fallback_conn.close()
            return _row_to_dict(fallback_cur, fallback_row) if fallback_row else None
        except Exception as fallback_error:
            _debug_log_throttled(
                key=f"word-note-read-fallback-failed:{os.path.abspath(target_path)}",
                msg=f"云端主连接兜底读取失败: {fallback_error}",
                interval_seconds=15.0,
                level="WARNING",
            )
            return None
    finally:
        try:
            c.close()
        except Exception:
            pass


def get_local_word_note(voc_id: str, db_path: str = None) -> Optional[dict]:
    """从本地副本读取单词笔记，使用共用的只读连接避免重复创建和 WAL 冲突。"""
    target_path = db_path or DB_PATH
    c = _get_read_conn(target_path)
    try:
        cur = c.cursor()
        cur.execute('SELECT * FROM ai_word_notes WHERE voc_id = ?', (str(voc_id),))
        r = cur.fetchone()
        return _row_to_dict(cur, r) if r else None
    except Exception as read_error:
        if _is_sqlite_data_corruption_error(read_error):
            _debug_log_throttled(
                key=f"local-word-note-read-corruption:{os.path.abspath(target_path)}",
                msg=f"本地单词读取命中损坏/乱码数据，返回空并交由上层兜底: {read_error}",
                interval_seconds=15.0,
                level="WARNING",
            )
            return None
        raise
    finally:
        try:
            c.close()
        except Exception:
            pass

def _matches_ai_generation_context(note_row: Dict[str, Any], ai_provider: Optional[str] = None, prompt_version: Optional[str] = None) -> bool:
    """判断笔记是否与当前 AI 生成上下文一致。"""
    current_provider = (ai_provider or "").strip().lower()
    current_prompt_version = (prompt_version or "").strip()

    batch_provider = str(
        note_row.get("batch_ai_provider")
        or note_row.get("ai_provider")
        or ""
    ).strip().lower()
    batch_prompt_version = str(
        note_row.get("batch_prompt_version")
        or note_row.get("prompt_version")
        or ""
    ).strip()

    # 工业级优化：如果调用者未指定过滤上下文（如批量回查），则不执行强制剔除
    if not current_provider:
        return True

    if current_provider and batch_provider != current_provider:
        return False

    if current_prompt_version and batch_prompt_version != current_prompt_version:
        return False

    return bool(batch_provider and batch_prompt_version)


def find_word_in_community(voc_id: str, ai_provider: str = None, prompt_version: str = None) -> Optional[Tuple[dict, str]]:
    """在社区数据库中查找单词笔记（优先云端，回退本地历史，最后查当前数据库）。"""
    # 1. 优先查询云端数据库
    if TURSO_DB_URL and TURSO_AUTH_TOKEN and HAS_LIBSQL:
        try:
            # 社区查询走读连接，避免创建第二个带 sync_url 的写连接/agent
            cloud_conn = _get_read_conn(DB_PATH)
            cloud_cur = cloud_conn.cursor()
            cloud_cur.execute(
                '''
                SELECT n.*, b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version
                FROM ai_word_notes n
                LEFT JOIN ai_batches b ON n.batch_id = b.batch_id
                WHERE n.voc_id = ?
                ''',
                (str(voc_id),)
            )
            r = cloud_cur.fetchone()
            if r:
                note_dict = _row_to_dict(cloud_cur, r)
                if _matches_ai_generation_context(note_dict, ai_provider=ai_provider, prompt_version=prompt_version):
                    return note_dict, "云端数据库"
        except Exception as e:
            _debug_log(f"云端社区查询失败: {e}")

    # 2. 回退查询本地历史数据库文件
    cdb = os.path.basename(DB_PATH)
    dr = os.path.dirname(DB_PATH)
    dfs = sorted([f for f in os.listdir(dr) if (f.startswith('history_') or f.startswith('history-')) and f.endswith('.db')],
                 key=lambda x: os.path.getmtime(os.path.join(dr, x)), reverse=True)

    for df in dfs:
        if df == cdb: continue
        try:
            c = _get_local_conn(os.path.join(dr, df))
            cur = c.cursor()
            cur.execute(
                '''
                SELECT n.*, b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version
                FROM ai_word_notes n
                LEFT JOIN ai_batches b ON n.batch_id = b.batch_id
                WHERE n.voc_id = ?
                ''',
                (str(voc_id),)
            )
            r = cur.fetchone()
            c.close()
            if r:
                note_dict = _row_to_dict(cur, r)
                if _matches_ai_generation_context(note_dict, ai_provider=ai_provider, prompt_version=prompt_version):
                    return note_dict, df
        except: continue

    # 3. 最后查询当前数据库
    try:
        c = _get_read_conn(DB_PATH)
        cur = c.cursor()
        cur.execute(
            '''
            SELECT n.*, b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version
            FROM ai_word_notes n
            LEFT JOIN ai_batches b ON n.batch_id = b.batch_id
            WHERE n.voc_id = ?
            ''',
            (str(voc_id),)
        )
        r = cur.fetchone()
        c.close()
        if r:
            note_dict = _row_to_dict(cur, r)
            if _matches_ai_generation_context(note_dict, ai_provider=ai_provider, prompt_version=prompt_version):
                return note_dict, "当前数据库"
    except: pass

    return None


def find_words_in_community_batch(
    voc_ids: List[str],
    skip_cloud: bool = False,
    ai_provider: str = None,
    prompt_version: str = None,
) -> Dict[str, Tuple[dict, str]]:
    """批量在社区数据库中查找单词笔记（优先本地历史/当前库，云端只补查剩余项）

    Args:
        voc_ids: 单词 ID 列表
        skip_cloud: 是否跳过云端查询（如果用户已合并数据，可设为 True）

    Returns:
        字典：voc_id -> (笔记数据, 来源)
    """
    if not voc_ids:
        return {}

    result = {}

    remaining_ids = [str(vid) for vid in voc_ids]

    # 1. 先查询本地历史数据库文件（只查未找到的单词）
    if remaining_ids:
        cdb = os.path.basename(DB_PATH)
        dr = os.path.dirname(DB_PATH)
        dfs = sorted([f for f in os.listdir(dr) if (f.startswith('history_') or f.startswith('history-')) and f.endswith('.db')],
                     key=lambda x: os.path.getmtime(os.path.join(dr, x)), reverse=True)

        for df in dfs:
            if df == cdb:
                continue
            try:
                c = _get_local_conn(os.path.join(dr, df))
                cur = c.cursor()
                placeholders = ','.join(['?'] * len(remaining_ids))
                cur.execute(
                    f'''
                    SELECT n.*, b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version
                    FROM ai_word_notes n
                    LEFT JOIN ai_batches b ON n.batch_id = b.batch_id
                    WHERE n.voc_id IN ({placeholders})
                    ''',
                    remaining_ids,
                )
                rows = cur.fetchall()
                c.close()

                if rows:
                    for row in rows:
                        note_dict = _row_to_dict(cur, row)
                        voc_id = note_dict.get('voc_id')
                        if voc_id and voc_id not in result and _matches_ai_generation_context(note_dict, ai_provider=ai_provider, prompt_version=prompt_version):
                            result[voc_id] = (note_dict, df)
                            if voc_id in remaining_ids:
                                remaining_ids.remove(voc_id)

                if not remaining_ids:
                    break
            except:
                continue

    # 2. 再查询当前数据库（只查未找到的单词）
    if remaining_ids:
        try:
            c = _get_read_conn(DB_PATH)
            cur = c.cursor()
            placeholders = ','.join(['?'] * len(remaining_ids))
            cur.execute(
                f'''
                SELECT n.*, b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version
                FROM ai_word_notes n
                LEFT JOIN ai_batches b ON n.batch_id = b.batch_id
                WHERE n.voc_id IN ({placeholders})
                ''',
                remaining_ids,
            )
            rows = cur.fetchall()
            c.close()

            if rows:
                for row in rows:
                    note_dict = _row_to_dict(cur, row)
                    voc_id = note_dict.get('voc_id')
                    if voc_id and voc_id not in result and _matches_ai_generation_context(note_dict, ai_provider=ai_provider, prompt_version=prompt_version):
                        result[voc_id] = (note_dict, "当前数据库")
                        if voc_id in remaining_ids:
                            remaining_ids.remove(voc_id)
        except:
            pass

    # 3. 云端只补查本地未命中的剩余单词
    if not skip_cloud and HAS_LIBSQL and remaining_ids:
        cloud_targets = _collect_cloud_lookup_targets()

        for cloud_url, cloud_token, source_label in cloud_targets:
            if not remaining_ids:
                break
            cloud_conn = None
            try:
                lookup_path = _get_cloud_lookup_replica_path(cloud_url)
                # 纯读路径禁止创建 sync_url 连接；仅使用本地副本文件读取。
                if not os.path.exists(lookup_path):
                    _debug_log(f"{source_label} 本地副本不存在，跳过纯读补查: {lookup_path}", level="DEBUG")
                    continue

                cloud_conn = libsql.connect(lookup_path)
                cloud_cur = cloud_conn.cursor()

                placeholders = ','.join(['?'] * len(remaining_ids))
                cloud_cur.execute(
                    f'''
                    SELECT n.*, b.ai_provider AS batch_ai_provider, b.prompt_version AS batch_prompt_version
                    FROM ai_word_notes n
                    LEFT JOIN ai_batches b ON n.batch_id = b.batch_id
                    WHERE n.voc_id IN ({placeholders})
                    ''',
                    remaining_ids,
                )
                rows = cloud_cur.fetchall()

                if rows:
                    columns = [col[0] for col in cloud_cur.description]
                    found_count = 0
                    for row in rows:
                        note_dict = dict(zip(columns, row))
                        voc_id = note_dict.get('voc_id')
                        if voc_id and voc_id not in result and _matches_ai_generation_context(note_dict, ai_provider=ai_provider, prompt_version=prompt_version):
                            result[voc_id] = (note_dict, source_label)
                            found_count += 1

                    if found_count:
                        remaining_ids = [vid for vid in remaining_ids if vid not in result]

                _debug_log(f"{source_label} 批量查询完成：累计找到 {len(result)} 个单词的笔记")
            except Exception as e:
                _debug_log(f"{source_label} 批量查询失败: {e}")
            finally:
                if cloud_conn:
                    try:
                        cloud_conn.close()
                    except Exception:
                        pass

    return result

def save_ai_batch(batch_data: dict, db_path: str = None):
    sql = 'INSERT OR REPLACE INTO ai_batches (batch_id, request_id, ai_provider, model_name, prompt_version, batch_size, total_latency_ms, prompt_tokens, completion_tokens, total_tokens, finish_reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
    args = (
        batch_data.get('batch_id'),
        batch_data.get('request_id'),
        batch_data.get('ai_provider'),
        batch_data.get('model_name'),
        batch_data.get('prompt_version'),
        batch_data.get('batch_size', 1),
        batch_data.get('total_latency_ms', 0),
        batch_data.get('prompt_tokens', 0),
        batch_data.get('completion_tokens', 0),
        batch_data.get('total_tokens', 0),
        batch_data.get('finish_reason'),
        get_timestamp_with_tz(),
    )
    if _should_use_local_only_connection(db_path):
        _execute_write_sql_sync(sql, args, db_path=db_path)
        return True
    if not _queue_write_operation(sql, args, op_type="insert_or_replace"):
        _debug_log("save_ai_batch 入队失败: 写队列已满", level="WARNING")
        return False
    return True


def _execute_write_sql(sql: str, params: tuple = (), db_path: str = None) -> None:
    """执行写 SQL（含 commit），用于消除重复样板代码。"""
    conn = _get_conn(db_path or DB_PATH)
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    _mark_main_db_needs_sync(db_path=db_path, conn=conn)
    if not _is_main_write_singleton_conn(conn):
        conn.close()


def _fetch_one_scalar(sql: str, params: tuple = (), db_path: str = None):
    """执行读 SQL 并返回首行首列。"""
    try:
        conn = _get_read_conn(db_path or DB_PATH)
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return row[0]
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            _debug_log_throttled(
                "fetch_one_scalar_corruption",
                f"_fetch_one_scalar 数据损坏异常: {e}",
                level="WARNING"
            )
            return None
        _debug_log(f"_fetch_one_scalar 异常: {e}", level="WARNING")
        return None


def get_file_hash(file_path):
    if not os.path.exists(file_path):
        return '00000000'
    with open(file_path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()[:8]

def archive_prompt_file(source_path, prompt_hash, prompt_type='main'):
    archive_dir = os.path.join(DATA_DIR, 'prompts')
    os.makedirs(archive_dir, exist_ok=True)
    target_path = os.path.join(archive_dir, f'prompt_{prompt_type}_{prompt_hash}.md')
    if not os.path.exists(target_path):
        shutil.copy2(source_path, target_path)

def get_latest_progress(voc_id, db_path=None):
    try:
        c = _get_read_conn(db_path or DB_PATH)
        cur = c.cursor()
        cur.execute(
            'SELECT familiarity_short, review_count FROM word_progress_history '
            'WHERE voc_id = ? ORDER BY created_at DESC LIMIT 1',
            (str(voc_id),)
        )
        r = cur.fetchone()
        c.close()
        return _row_to_dict(cur, r) if r else None
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            _debug_log_throttled(
                "get_latest_progress_corruption",
                f"get_latest_progress 数据损坏异常: {e}",
                level="WARNING"
            )
            return None
        _debug_log(f"get_latest_progress 异常: {e}", level="WARNING")
        return None

def set_config(k, v, db=None):
    sql = 'INSERT OR REPLACE INTO system_config (key, value, updated_at) VALUES (?, ?, ?)'
    args = (k, v, get_timestamp_with_tz())
    if _should_use_local_only_connection(db):
        _execute_write_sql_sync(sql, args, db_path=db)
        return True
    if not _queue_write_operation(sql, args, op_type="insert_or_replace"):
        _debug_log("set_config 入队失败: 写队列已满", level="WARNING")
        return False
    return True


def initialize_local_database_file(db_path: str) -> bool:
    """初始化指定路径的本地数据库文件（供业务层安全复用，避免直连 sqlite3）。"""
    try:
        conn = _get_local_conn(db_path)
        cur = conn.cursor()
        _create_tables(cur)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        _debug_log(f"initialize_local_database_file 失败: {e}", level="WARNING")
        return False


def get_config(k, db=None):
    return _fetch_one_scalar(
        'SELECT value FROM system_config WHERE key = ?',
        (k,),
        db_path=(db or DB_PATH),
    )


def save_test_word_note(v, p):
    save_ai_word_note(v, p, db_path=TEST_DB_PATH)


def log_test_run(
    t=None,
    s=None,
    w=None,
    a=None,
    sp=None,
    d=True,
    e="",
    res=None,
    **kwargs,
):
    """记录测试运行日志，兼容旧的 positional 调用和新的 keyword 调用。"""
    if t is None:
        t = kwargs.pop("total_count", None)
    if s is None:
        s = kwargs.pop("sample_count", None)
    if w is None:
        w = kwargs.pop("words_sampled", None)
    if a is None:
        a = kwargs.pop("ai_calls", None)
    if sp is None:
        sp = kwargs.pop("success_parsed", None)

    if "is_dry_run" in kwargs:
        d = kwargs.pop("is_dry_run")
    if "error_msg" in kwargs:
        e = kwargs.pop("error_msg")
    if "ai_results" in kwargs:
        res = kwargs.pop("ai_results")

    if kwargs:
        _debug_log(f"log_test_run 收到未使用参数: {sorted(kwargs.keys())}", level="DEBUG")

    if t is None or s is None or w is None or a is None or sp is None:
        raise TypeError("log_test_run 缺少必要参数")

    if isinstance(w, (list, tuple)):
        words_sampled = ",".join(str(item) for item in w)
    else:
        words_sampled = str(w)

    c = _get_conn(TEST_DB_PATH)
    cur = c.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS test_run_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total_count INTEGER,
            sample_count INTEGER,
            sample_words TEXT,
            ai_calls INTEGER,
            success_parsed INTEGER,
            is_dry_run BOOLEAN,
            error_msg TEXT,
            ai_results_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    aj = json.dumps(res, ensure_ascii=False) if res else ""
    cur.execute(
        'INSERT INTO test_run_logs '
        '(total_count, sample_count, sample_words, ai_calls, success_parsed, is_dry_run, error_msg, ai_results_json) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (t, s, words_sampled, a, sp, d, e, aj)
    )
    c.commit()
    rid = cur.lastrowid
    c.close()
    return rid


def _emit_sync_progress(progress_callback, stage: str, current: int, total: int, message: str, **extra):
    """统一同步进度事件出口，避免回调异常影响主流程。"""
    if not progress_callback:
        return
    payload = {
        "stage": stage,
        "current": current,
        "total": total,
        "message": message,
    }
    if extra:
        payload.update(extra)
    try:
        progress_callback(payload)
    except Exception:
        pass


def _is_cloud_connection_unavailable_error(error: Exception) -> bool:
    """判断是否为云端连接不可用或被强制云端模式拦截的错误。"""
    msg = str(error or "").lower()
    return (
        "强制云端模式已启用" in str(error or "")
        or "cannot connect to the cloud" in msg
        or "unable to connect" in msg
        or "failed to connect" in msg
        or "cloud" in msg and "unavailable" in msg
    )

@log_performance(lambda: ContextLogger(logging.getLogger(__name__)))
def sync_databases(
    db_path: str = None,
    dry_run: bool = False,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, int]:
    """数据库同步 - Embedded Replicas 版本
    
    Embedded Replicas 使用 libsql 内置的 conn.sync() 方法自动同步本地副本和远程主库。
    
    Args:
        db_path: 数据库路径
        dry_run: 干运行模式（检查但不提交）
        progress_callback: 进度回调函数
    
    Returns:
        同步统计信息 {'upload': 0, 'download': 0, 'status': 'ok|skipped|error', ...}
    """
    path = db_path or DB_PATH
    stats = {'upload': 0, 'download': 0, 'status': 'ok', 'reason': ''}
    
    # 纯本地模式时跳过同步
    if not TURSO_DB_URL or not TURSO_AUTH_TOKEN or not HAS_LIBSQL:
        stats['status'] = 'skipped'
        if not TURSO_DB_URL or not TURSO_AUTH_TOKEN:
            stats['reason'] = 'missing-cloud-credentials'
        else:
            stats['reason'] = 'libsql-unavailable'
        _debug_log(f"云端未配置或不可用，跳过同步: {stats['reason']}")
        _emit_sync_progress(progress_callback, 'skipped', 0, 0, f"跳过同步: {stats['reason']}", status='skipped', reason=stats['reason'])
        return stats
    
    sync_start = time.time()
    if not dry_run: 
        _debug_log("开始数据库同步（Embedded Replicas）...")
    
    try:
        _emit_sync_progress(progress_callback, 'connect', 1, 2, '连接 Embedded Replica 数据库')
        
        try:
            # 主库同步统一复用全局单例写连接，确保只有一个 sync agent
            if _is_main_db_path(path):
                conn = _get_main_write_conn_singleton(do_sync=False)
            else:
                # 非主库仍保持原逻辑
                conn = _get_conn(path, do_sync=False)
        except Exception as conn_error:
            if _is_cloud_connection_unavailable_error(conn_error):
                stats['status'] = 'skipped'
                stats['reason'] = 'cloud-unavailable'
                _emit_sync_progress(progress_callback, 'skipped', 0, 0, f"跳过同步: {conn_error}", status='skipped', reason=stats['reason'])
                return stats
            raise
        
        # 检查是否为 Embedded Replica 连接（有 sync() 方法）
        if not hasattr(conn, 'sync'):
            # 纯本地连接，无需同步
            stats['status'] = 'skipped'
            stats['reason'] = 'local-only-connection'
            _emit_sync_progress(progress_callback, 'done', 1, 2, '本地模式，无需同步', status='skipped')
            return stats
        
        _emit_sync_progress(progress_callback, 'sync', 1, 2, '执行帧级增量同步...')
        
        if not dry_run:
            # 执行同步：Turso 在服务器端跟踪每个副本的同步点位，
            # 每次 sync() 只传输客户端未见过的新帧，实现高效的增量同步
            with _main_write_conn_op_lock:
                sync_result = conn.sync()
            _debug_log(f"同步完成: {sync_result}")
            
            # 为了兼容原有的统计信息格式，这里返回一个通用的"已同步"标记
            # 在真实应用中，可以通过其他方式计算精确的上传/下载行数
            # 这里使用一个简单的启发式方法：如果 sync() 没有异常，认为已同步
            stats['upload'] = 0  # Embedded Replicas 自动处理，不需要显式统计
            stats['download'] = 0
            stats['frames_synced'] = getattr(sync_result, 'frames_synced', 0) if sync_result else 0
        
        _emit_sync_progress(progress_callback, 'done', 2, 2, '同步完成', upload=0, download=0)
        
        total_time = int((time.time() - sync_start) * 1000)
        stats['duration_ms'] = total_time
        stats['status'] = 'ok'
        
        if not dry_run:
            _debug_log(f"数据库同步完成 | 总耗时: {total_time}ms")
        
        return stats
        
    except Exception as e:
        _debug_log(f"数据库同步失败: {e}")
        stats['status'] = 'error'
        stats['reason'] = str(e)
        _emit_sync_progress(progress_callback, 'error', 0, 0, f"同步失败: {e}", status='error', reason=str(e))
        return stats

def _row_to_dict(cursor, row) -> dict:
    """将任意 row 对象（sqlite3.Row 或 libsql tuple）安全转换为 dict。"""
    if isinstance(row, dict):
        return row
    if hasattr(row, 'asdict'):
        try:
            return row.asdict()
        except Exception:
            pass

    try:
        # sqlite3.Row: keys() 方法
        return dict(zip(row.keys(), tuple(row)))
    except AttributeError:
        if hasattr(row, 'astuple') and hasattr(cursor, 'description') and cursor.description:
            cols = [d[0] for d in cursor.description]
            return dict(zip(cols, row.astuple()))
        # libsql 返回 tuple，用 cursor.description 获取列名
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))


# ============================================================================
# 中央用户数据库（Users Hub）相关函数
# ============================================================================

def is_hub_configured() -> bool:
    """检查中央 Hub 数据库是否配置了云端凭据"""
    return bool(TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN)

def _get_hub_conn(max_retries: int = 3, retry_delay: float = 1.0) -> Any:
    """获取中央用户 Hub 数据库连接（优先云端 Turso，无配置则回退本地 SQLite）

    Args:
        max_retries: 最大重试次数（默认 3 次）
        retry_delay: 每次重试的延迟秒数（默认 1.0 秒）
    """
    # 强制云端模式检查
    from config import get_force_cloud_mode
    if get_force_cloud_mode() and not is_hub_configured():
        raise RuntimeError("强制云端模式已启用，但未配置 TURSO_HUB_DB_URL 或 TURSO_HUB_AUTH_TOKEN。请在 .env 文件中配置，或将 FORCE_CLOUD_MODE 设置为 False 以允许本地运行。")
    if get_force_cloud_mode() and not HAS_LIBSQL:
        raise RuntimeError("强制云端模式已启用，但 libsql 不可用。请先安装/启用 libsql 依赖后再连接云端 Hub 数据库。")

    # 优先尝试云端（带重试机制）
    if TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN and HAS_LIBSQL:
        last_error = None
        for attempt in range(max_retries):
            try:
                _debug_log(f"尝试连接云端 Hub (第 {attempt + 1}/{max_retries} 次)")
                return _get_hub_write_conn_singleton(do_sync=False, max_retries=max_retries, retry_delay=retry_delay)
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:  # 不是最后一次尝试
                    _debug_log(f"云端连接失败 (尝试 {attempt + 1})，{retry_delay} 秒后重试: {e}")
                    time.sleep(retry_delay)
                else:
                    _debug_log(f"云端连接失败 (已尝试 {max_retries} 次)，回退本地: {e}")

        if get_force_cloud_mode():
            # 强制模式下，连接失败直接抛出异常
            raise RuntimeError(f"强制云端模式连接 Hub 失败 (已尝试 {max_retries} 次): {last_error}")

    # 非强制模式下，无配置或失败时回退到本地
    if not get_force_cloud_mode():
        _debug_log("回退到本地 Hub 数据库")
        return _get_hub_local_conn()

    # 强制模式下如果到这里说明配置有问题
    raise RuntimeError("强制云端模式已启用，但无法连接到云端 Hub 数据库")


def _get_hub_local_conn() -> sqlite3.Connection:
    """获取 Hub 本地连接，并在损坏时执行与用户库同等级的自愈。"""
    path = HUB_DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def _open_local_connection() -> sqlite3.Connection:
        conn = sqlite3.connect(path, timeout=20.0)
        conn.row_factory = sqlite3.Row
        conn.text_factory = lambda b: b.decode("utf-8", "replace")
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")  # 5秒自动重试WAL锁定冲突
        return conn

    try:
        return _open_local_connection()
    except (sqlite3.DatabaseError, sqlite3.OperationalError) as error:
        if not _is_sqlite_malformed_error(error):
            raise

        backup_path = _backup_broken_database_file(path, "检测到 Hub 本地数据库损坏，已备份本地数据库")
        if not backup_path:
            raise

        if HAS_LIBSQL and TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN:
            try:
                _debug_log(f"Hub 本地数据库损坏后，尝试通过云端副本重建: {path}", level="WARNING")
                return _get_hub_write_conn_singleton(do_sync=True)
            except Exception as recovery_error:
                _debug_log(f"通过云端副本重建 Hub 本地数据库失败，改为重新初始化空库: {recovery_error}", level="WARNING")

        conn = _open_local_connection()
        try:
            _init_hub_schema(conn)
            conn.commit()
        except Exception as init_error:
            try:
                conn.close()
            except Exception:
                pass
            raise RuntimeError(f"Hub 本地数据库重建失败: {init_error}")
        return conn

def init_users_hub_tables() -> bool:
    """初始化中央用户 Hub 数据库的6个表"""
    try:
        hub_fp = _hub_db_fingerprint()
        # 命中近期成功的初始化状态时，直接短路，避免每次启动都重复做 Hub 握手和 schema 校验
        if _hub_init_state_is_fresh(hub_fp):
            _debug_log("Hub 数据库已在有效缓存窗口内初始化，跳过重复 schema 校验")
            return True

        # 即使存在旧式初始化标记，也继续执行 CREATE IF NOT EXISTS，确保新增表/列能自动补齐
        if _is_db_initialized("hub", hub_fp):
            _debug_log("Hub 数据库已初始化（通过旧标记文件），执行轻量 schema 校验")

        hub_start = time.time()
        hub_conn = _get_hub_conn()
        _debug_log("Hub 数据库连接完成", hub_start)

        cur = hub_conn.cursor()

        # 检查表是否已存在（避免重复执行耗时的 CREATE TABLE 操作）
        check_start = time.time()
        table_exists = _check_table_exists(cur, "users", "hub", cache_scope=hub_fp)
        _debug_log(f"Hub 表存在检查完成 (存在: {table_exists})", check_start)

        if table_exists:
            _debug_log("中央 Hub users 表已存在，将执行增量 schema 校验")

        # 1. users 表：基本用户信息及角色/状态
        with _hub_write_conn_op_lock:
            cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                first_login_at TEXT,
                last_login_at TEXT,
                status TEXT DEFAULT 'active',
                role TEXT DEFAULT 'user',
                notes TEXT,
                updated_at TEXT
            )
            ''')
        
        try:
            with _hub_write_conn_op_lock:
                cur.execute("ALTER TABLE users ADD COLUMN updated_at TEXT")
        except: pass
        
        # 2. user_api_keys 表：用户 API 密钥（加密存储）
        with _hub_write_conn_op_lock:
            cur.execute('''
            CREATE TABLE IF NOT EXISTS user_api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                api_key_encrypted TEXT NOT NULL,
                api_key_name TEXT,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                revoked_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
            ''')
        
        # 3. user_sync_history 表：用户数据同步历史
        with _hub_write_conn_op_lock:
            cur.execute('''
            CREATE TABLE IF NOT EXISTS user_sync_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                sync_type TEXT NOT NULL,
                source TEXT,
                target TEXT,
                record_count INTEGER,
                sync_status TEXT,
                error_msg TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
            ''')
        
        # 4. user_stats 表：用户统计信息（缓存）
        with _hub_write_conn_op_lock:
            cur.execute('''
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id TEXT PRIMARY KEY,
                total_words_processed INTEGER DEFAULT 0,
                total_ai_calls INTEGER DEFAULT 0,
                total_prompt_tokens INTEGER DEFAULT 0,
                total_completion_tokens INTEGER DEFAULT 0,
                total_sync_count INTEGER DEFAULT 0,
                last_activity_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
            ''')
        
        # 5. user_sessions 表：用户会话跟踪
        with _hub_write_conn_op_lock:
            cur.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                session_id TEXT UNIQUE NOT NULL,
                client_info TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                login_at TEXT NOT NULL,
                logout_at TEXT,
                last_activity_at TEXT,
                session_status TEXT DEFAULT 'active',
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
            ''')
        
        # 6. admin_logs 表：管理员操作日志
        with _hub_write_conn_op_lock:
            cur.execute('''
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                action_detail TEXT,
                admin_username TEXT,
                target_user_id TEXT,
                timestamp TEXT NOT NULL,
                result TEXT DEFAULT 'success'
            )
            ''')

        # 7. user_credentials 表：用户敏感配置（加密存储）
        with _hub_write_conn_op_lock:
            cur.execute('''
            CREATE TABLE IF NOT EXISTS user_credentials (
                user_id TEXT PRIMARY KEY,
                turso_db_url_enc TEXT,
                turso_auth_token_enc TEXT,
                momo_token_enc TEXT,
                mimo_api_key_enc TEXT,
                gemini_api_key_enc TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
            ''')

        with _hub_write_conn_op_lock:
            hub_conn.commit()
        if not _is_hub_write_singleton_conn(hub_conn):
            hub_conn.close()
        _debug_log("中央 Hub 数据库表初始化完成")
        # 标记数据库已初始化
        _mark_db_initialized("hub", hub_fp)
        _save_hub_init_state({
            "hub_fp": hub_fp,
            "schema_version": _HUB_SCHEMA_VERSION,
            "last_success_at": time.time(),
            "last_checked_at": time.time(),
            "mode": "cloud" if TURSO_HUB_DB_URL else "local",
        })
        return True
        
    except Exception as e:
        _debug_log(f"初始化中央 Hub 表失败: {e}")
        return False

def save_user_info_to_hub(user_id: str, username: str, email: str, user_notes: str = "", role: str = "user", conn: Any = None) -> bool:
    """
    保存用户信息到中央 Hub 数据库

    Args:
        user_id: 唯一用户 ID (通常为 UUID)
        username: 用户名
        email: 邮箱
        user_notes: 可选的用户备注
        role: 用户角色（默认 user，Asher 自动成为 admin）
        conn: 可选的数据库连接（用于复用连接）
    """
    try:
        def _do_sql(hub_conn):
            cur = hub_conn.cursor()

            timestamp = get_timestamp_with_tz()
            normalized_username = username.strip().lower()
            final_role = role
            if normalized_username.lower() == 'asher':
                final_role = 'admin'

            existing = None
            if user_id:
                cur.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
                existing = cur.fetchone()
            if not existing:
                cur.execute('SELECT * FROM users WHERE lower(username) = ?', (normalized_username,))
                existing = cur.fetchone()

            existing_data = _row_to_dict(cur, existing) if existing else {}
            inserted_user_id = existing_data.get('user_id', user_id)
            created_at = existing_data.get('created_at', timestamp)
            first_login_at = existing_data.get('first_login_at')
            last_login_at = existing_data.get('last_login_at')
            existing_role = existing_data.get('role')
            if existing_role and existing_role.lower() == 'admin':
                final_role = 'admin'
            status = existing_data.get('status', 'active')

            cur.execute('''
                INSERT OR REPLACE INTO users (user_id, username, email, created_at, first_login_at, last_login_at, status, role, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                inserted_user_id,
                normalized_username,
                email,
                created_at,
                first_login_at,
                last_login_at,
                status,
                final_role,
                user_notes,
                timestamp
            ))

            return normalized_username, inserted_user_id

        normalized_username, inserted_user_id = _run_with_managed_connection(conn, _get_hub_conn, _do_sql)

        _debug_log(f"用户信息已保存到 Hub: {normalized_username} ({inserted_user_id})")
        return True

    except Exception as e:
        _debug_log(f"保存用户信息到 Hub 失败: {e}")
        return False

def save_user_credentials_to_hub(user_id: str, credentials: Dict[str, str], conn: Any = None) -> bool:
    """保存用户敏感凭据到 Hub（字段加密后落库）。"""
    if not user_id:
        return False
    if not credentials:
        return True

    key_bytes = _get_secret_key_bytes()
    if not key_bytes:
        _debug_log("跳过保存 Hub 凭据：ENCRYPTION_KEY 未配置", level="WARNING")
        return False

    field_map = {
        "turso_db_url": "turso_db_url_enc",
        "turso_auth_token": "turso_auth_token_enc",
        "momo_token": "momo_token_enc",
        "mimo_api_key": "mimo_api_key_enc",
        "gemini_api_key": "gemini_api_key_enc",
    }

    try:
        def _do_sql(hub_conn):
            cur = hub_conn.cursor()
            cur.execute('SELECT * FROM user_credentials WHERE user_id = ?', (user_id,))
            existing = cur.fetchone()
            existing_data = _row_to_dict(cur, existing) if existing else {}

            now = get_timestamp_with_tz()
            created_at = existing_data.get('created_at', now)

            row_values = {
                "user_id": user_id,
                "created_at": created_at,
                "updated_at": now,
            }

            for src_key, db_col in field_map.items():
                candidate = credentials.get(src_key)
                if candidate:
                    row_values[db_col] = _encrypt_secret_value(str(candidate))
                else:
                    row_values[db_col] = existing_data.get(db_col)

            cur.execute('''
                INSERT OR REPLACE INTO user_credentials (
                    user_id, turso_db_url_enc, turso_auth_token_enc, momo_token_enc,
                    mimo_api_key_enc, gemini_api_key_enc, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                row_values["user_id"],
                row_values.get("turso_db_url_enc"),
                row_values.get("turso_auth_token_enc"),
                row_values.get("momo_token_enc"),
                row_values.get("mimo_api_key_enc"),
                row_values.get("gemini_api_key_enc"),
                row_values["created_at"],
                row_values["updated_at"],
            ))

        _run_with_managed_connection(conn, _get_hub_conn, _do_sql)

        _debug_log(f"用户凭据已更新到 Hub: {user_id}")
        return True
    except Exception as e:
        _debug_log(f"保存用户凭据到 Hub 失败: {e}")
        return False


def _hub_fetch_one_dict(sql: str, params: tuple = ()) -> Optional[dict]:
    """执行 Hub 查询并返回单条字典记录。"""
    try:
        if TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN and HAS_LIBSQL:
            hub_conn = _get_libsql_local_read_conn(HUB_DB_PATH)
        else:
            hub_conn = _get_hub_local_conn()
        cur = hub_conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        hub_conn.close()
        return _row_to_dict(cur, row) if row else None
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            _debug_log_throttled(
                "hub_fetch_one_dict_corruption",
                f"_hub_fetch_one_dict 数据损坏异常: {e}",
                level="WARNING"
            )
            return None
        _debug_log(f"_hub_fetch_one_dict 异常: {e}", level="WARNING")
        return None


def _hub_fetch_all_dicts(sql: str, params: tuple = ()) -> List[dict]:
    """执行 Hub 查询并返回字典列表。"""
    try:
        if TURSO_HUB_DB_URL and TURSO_HUB_AUTH_TOKEN and HAS_LIBSQL:
            hub_conn = _get_libsql_local_read_conn(HUB_DB_PATH)
        else:
            hub_conn = _get_hub_local_conn()
        cur = hub_conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        hub_conn.close()
        return [_row_to_dict(cur, row) for row in rows]
    except Exception as e:
        if _is_sqlite_data_corruption_error(e):
            _debug_log_throttled(
                "hub_fetch_all_dicts_corruption",
                f"_hub_fetch_all_dicts 数据损坏异常: {e}",
                level="WARNING"
            )
            return []
        _debug_log(f"_hub_fetch_all_dicts 异常: {e}", level="WARNING")
        return []

def get_user_credentials_from_hub(user_id: str, decrypt_values: bool = False) -> Optional[dict]:
    """读取 Hub 中的用户凭据；可选解密返回明文。"""
    if not user_id:
        return None
    try:
        data = _hub_fetch_one_dict('SELECT * FROM user_credentials WHERE user_id = ?', (user_id,))
        if not data:
            return None

        if not decrypt_values:
            return data

        out = {
            "user_id": data.get("user_id"),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }
        decrypt_map = {
            "turso_db_url": data.get("turso_db_url_enc"),
            "turso_auth_token": data.get("turso_auth_token_enc"),
            "momo_token": data.get("momo_token_enc"),
            "mimo_api_key": data.get("mimo_api_key_enc"),
            "gemini_api_key": data.get("gemini_api_key_enc"),
        }
        for k, v in decrypt_map.items():
            out[k] = _decrypt_secret_value(v) if v else ""
        return out
    except Exception as e:
        _debug_log(f"读取用户凭据失败: {e}")
        return None

def get_user_by_username(username: str) -> Optional[dict]:
    """从 Hub 按 username 查询用户记录。"""
    try:
        return _hub_fetch_one_dict('SELECT * FROM users WHERE lower(username) = ?', (username.strip().lower(),))
    except Exception as e:
        _debug_log(f"从 Hub 按用户名查询失败: {e}")
        return None

def is_admin_username(username: str) -> bool:
    """判断指定用户名是否具有管理员角色。"""
    if not username:
        return False
    normalized = username.strip().lower()
    if normalized == 'asher':
        return True
    user = get_user_by_username(username)
    return bool(user and user.get('role', '').lower() == 'admin')

def list_hub_users(limit: int = 50) -> List[dict]:
    """列出 Hub 中的用户信息。"""
    try:
        return _hub_fetch_all_dicts(
            'SELECT user_id, username, email, role, status, created_at, last_login_at FROM users ORDER BY created_at ASC LIMIT ?',
            (limit,),
        )
    except Exception as e:
        _debug_log(f"获取 Hub 用户列表失败: {e}")
        return []

def set_user_status(user_id: str, status: str = 'active') -> bool:
    """修改 Hub 中用户的状态。"""
    if status not in ('active', 'disabled', 'suspended'):
        raise ValueError('非法状态值')
    try:
        def _do_sql(hub_conn):
            cur = hub_conn.cursor()
            cur.execute('UPDATE users SET status = ? WHERE user_id = ?', (status, user_id))
            return cur.rowcount

        updated = _run_with_managed_connection(None, _get_hub_conn, _do_sql)
        _debug_log(f"用户状态已修改: {user_id} -> {status}")
        return updated > 0
    except Exception as e:
        _debug_log(f"修改用户状态失败: {e}")
        return False

def list_admin_logs(limit: int = 25) -> List[dict]:
    """获取最近的管理员操作日志。"""
    try:
        return _hub_fetch_all_dicts('SELECT * FROM admin_logs ORDER BY id DESC LIMIT ?', (limit,))
    except Exception as e:
        _debug_log(f"获取管理员日志失败: {e}")
        return []

def save_user_session(user_id: str, session_id: str, client_info: str, ip_address: str, conn: Any = None) -> bool:
    """
    记录用户登录会话

    Args:
        user_id: 用户 ID
        session_id: 会话 ID
        client_info: 客户端信息（JSON 格式）
        ip_address: 用户 IP 地址
        conn: 可选的数据库连接（用于复用连接）
    """
    try:
        def _do_sql(hub_conn):
            cur = hub_conn.cursor()
            login_at = get_timestamp_with_tz()
            cur.execute('''
                INSERT INTO user_sessions (user_id, session_id, client_info, ip_address, login_at, last_activity_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, session_id, client_info, ip_address, login_at, login_at))

        _run_with_managed_connection(conn, _get_hub_conn, _do_sql)

        _debug_log(f"用户会话已记录: {user_id} from {ip_address}")
        return True

    except Exception as e:
        _debug_log(f"保存用户会话失败: {e}")
        return False

def update_user_stats(user_id: str, words_count: int = 0, ai_calls: int = 0, 
                     prompt_tokens: int = 0, completion_tokens: int = 0) -> bool:
    """
    更新用户统计信息（累加）
    
    Args:
        user_id: 用户 ID
        words_count: 处理的词汇数
        ai_calls: AI 调用次数
        prompt_tokens: Prompt token 数量
        completion_tokens: Completion token 数量
    """
    try:
        def _do_sql(hub_conn):
            cur = hub_conn.cursor()

            updated_at = get_timestamp_with_tz()

            # 先查询现有数据
            cur.execute('SELECT * FROM user_stats WHERE user_id = ?', (user_id,))
            row = cur.fetchone()

            if row:
                # 更新（累加）
                row_dict = _row_to_dict(cur, row)
                new_words = row_dict.get('total_words_processed', 0) + words_count
                new_calls = row_dict.get('total_ai_calls', 0) + ai_calls
                new_prompt = row_dict.get('total_prompt_tokens', 0) + prompt_tokens
                new_completion = row_dict.get('total_completion_tokens', 0) + completion_tokens

                cur.execute('''
                    UPDATE user_stats
                    SET total_words_processed = ?,
                        total_ai_calls = ?,
                        total_prompt_tokens = ?,
                        total_completion_tokens = ?,
                        last_activity_at = ?,
                        updated_at = ?
                    WHERE user_id = ?
                ''', (new_words, new_calls, new_prompt, new_completion, updated_at, updated_at, user_id))
            else:
                # 新增
                cur.execute('''
                    INSERT INTO user_stats (user_id, total_words_processed, total_ai_calls,
                                           total_prompt_tokens, total_completion_tokens,
                                           last_activity_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, words_count, ai_calls, prompt_tokens, completion_tokens, updated_at, updated_at))

        _run_with_managed_connection(None, _get_hub_conn, _do_sql)
        _debug_log(f"用户统计已更新: {user_id}")
        return True
        
    except Exception as e:
        _debug_log(f"更新用户统计失败: {e}")
        return False

def log_admin_action(action_type: str, action_detail: str = "", admin_username: str = "",
                    target_user_id: str = "", result: str = "success", conn: Any = None) -> bool:
    """
    记录管理员操作日志

    Args:
        action_type: 操作类型（如 'create_database', 'verify_password', 'user_created'）
        action_detail: 操作详情
        admin_username: 管理员用户名
        target_user_id: 目标用户 ID（如果有）
        result: 操作结果（'success' 或 'failure'）
        conn: 可选的数据库连接（用于复用连接）
    """
    try:
        def _do_sql(hub_conn):
            cur = hub_conn.cursor()
            timestamp = get_timestamp_with_tz()
            cur.execute('''
                INSERT INTO admin_logs (action_type, action_detail, admin_username, target_user_id, timestamp, result)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (action_type, action_detail, admin_username, target_user_id, timestamp, result))

        _run_with_managed_connection(conn, _get_hub_conn, _do_sql)

        _debug_log(f"管理员操作已记录: {action_type}")
        return True

    except Exception as e:
        _debug_log(f"记录管理员操作失败: {e}")
        return False

def update_user_login_time(user_id: str, conn: Any = None) -> bool:
    """更新用户最后登录时间"""
    try:
        def _do_sql(hub_conn):
            cur = hub_conn.cursor()
            login_time = get_timestamp_with_tz()
            cur.execute('''
                UPDATE users
                SET last_login_at = ?, first_login_at = COALESCE(first_login_at, ?)
                WHERE user_id = ?
            ''', (login_time, login_time, user_id))

        _run_with_managed_connection(conn, _get_hub_conn, _do_sql)

        return True

    except Exception as e:
        _debug_log(f"更新用户登录时间失败: {e}")
        return False

def get_user_from_hub(user_id: str) -> Optional[dict]:
    """从中央 Hub 获取用户信息"""
    try:
        return _hub_fetch_one_dict('SELECT * FROM users WHERE user_id = ?', (user_id,))
        
    except Exception as e:
        _debug_log(f"从 Hub 获取用户信息失败: {e}")
        return None

def sync_hub_databases(
    dry_run: bool = False,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """同步中央 Hub 数据库 - Embedded Replicas 版本
    
    使用 Embedded Replicas 的 conn.sync() 方法实现高效的增量同步。
    
    Args:
        dry_run: 干运行模式（检查但不提交）
        progress_callback: 进度回调函数
    
    Returns:
        同步统计信息 {'upload': 0, 'download': 0, 'status': 'ok|skipped|error', ...}
    """
    stats = {'upload': 0, 'download': 0, 'status': 'ok', 'reason': ''}
    sync_start = time.time()
    
    # 检查 Hub 凭据
    if not TURSO_HUB_DB_URL or not TURSO_HUB_AUTH_TOKEN or not HAS_LIBSQL:
        stats['status'] = 'skipped'
        if not TURSO_HUB_DB_URL or not TURSO_HUB_AUTH_TOKEN:
            stats['reason'] = 'missing-hub-cloud-credentials'
        else:
            stats['reason'] = 'libsql-unavailable'
        _emit_sync_progress(progress_callback, 'skipped', 0, 0, '跳过 Hub 同步: 云端凭据或 libsql 不可用', status='skipped')
        return stats
    
    _curr_logger = get_logger()
    if not dry_run:
        _curr_logger.debug("正在同步中央 Hub 数据库（Embedded Replicas）...", module="db_manager")
    
    try:
        _emit_sync_progress(progress_callback, 'connect', 1, 2, '连接 Hub Embedded Replica 数据库')
        
        # 初始化本地 Hub 表结构（确保表存在）
        try:
            local_hub_conn = _get_hub_local_conn()
            _init_hub_schema(local_hub_conn)
            local_hub_conn.close()
        except Exception as e:
            _debug_log(f"Hub 本地表初始化警告（非致命）: {e}")
        
        # 获取 Hub 的 Embedded Replica 连接
        try:
            hub_conn = _get_hub_conn()
        except Exception as conn_error:
            if _is_cloud_connection_unavailable_error(conn_error):
                stats['status'] = 'skipped'
                stats['reason'] = 'cloud-unavailable'
                _emit_sync_progress(progress_callback, 'skipped', 0, 0, f"跳过 Hub 同步: {conn_error}", status='skipped', reason=stats['reason'])
                return stats
            raise
        
        # 检查是否为 Embedded Replica 连接（有 sync() 方法）
        if not hasattr(hub_conn, 'sync'):
            # 纯本地 Hub 连接，无需同步
            stats['status'] = 'skipped'
            stats['reason'] = 'local-only-hub-connection'
            _emit_sync_progress(progress_callback, 'done', 1, 2, 'Hub 本地模式，无需同步', status='skipped')
            return stats
        
        _emit_sync_progress(progress_callback, 'sync', 1, 2, '执行 Hub 帧级增量同步...')
        
        if not dry_run:
            # 执行 Hub 同步
            with _hub_write_conn_op_lock:
                sync_result = hub_conn.sync()
            _debug_log(f"Hub 同步完成: {sync_result}")
            stats['frames_synced'] = getattr(sync_result, 'frames_synced', 0) if sync_result else 0
        
        _emit_sync_progress(progress_callback, 'done', 2, 2, 'Hub 同步完成', upload=0, download=0)
        
        total_time = int((time.time() - sync_start) * 1000)
        stats['duration_ms'] = total_time
        stats['status'] = 'ok'
        
        if not dry_run:
            _curr_logger.debug(f"Hub 同步完成 | 耗时 {total_time}ms", module="db_manager")
        
        return stats
        
    except Exception as e:
        _debug_log(f"Hub 同步失败: {e}")
        stats['status'] = 'error'
        stats['reason'] = str(e)
        _emit_sync_progress(progress_callback, 'error', 0, 0, f"Hub 同步失败: {e}", status='error', reason=str(e))
        return stats


def _init_hub_schema(conn: sqlite3.Connection):
    """初始化 Hub 本地表结构"""
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            first_login_at TEXT,
            last_login_at TEXT,
            status TEXT DEFAULT 'active',
            role TEXT DEFAULT 'user',
            notes TEXT,
            updated_at TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS user_auth (
            user_id TEXT PRIMARY KEY,
            password_hash TEXT,
            auth_type TEXT DEFAULT 'local',
            failed_attempts INTEGER DEFAULT 0,
            last_failed_at TEXT,
            last_password_change TEXT,
            must_change_password INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS user_sync_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            sync_type TEXT NOT NULL,
            source TEXT,
            target TEXT,
            record_count INTEGER,
            sync_status TEXT,
            error_msg TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id TEXT PRIMARY KEY,
            total_words_processed INTEGER DEFAULT 0,
            total_ai_calls INTEGER DEFAULT 0,
            total_prompt_tokens INTEGER DEFAULT 0,
            total_completion_tokens INTEGER DEFAULT 0,
            total_sync_count INTEGER DEFAULT 0,
            last_activity_at TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS user_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            session_id TEXT UNIQUE NOT NULL,
            client_info TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            login_at TEXT NOT NULL,
            logout_at TEXT,
            last_activity_at TEXT,
            session_status TEXT DEFAULT 'active',
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT NOT NULL,
            action_detail TEXT,
            admin_username TEXT,
            target_user_id TEXT,
            timestamp TEXT NOT NULL,
            result TEXT DEFAULT 'success'
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS user_credentials (
            user_id TEXT PRIMARY KEY,
            turso_db_url_enc TEXT,
            turso_auth_token_enc TEXT,
            momo_token_enc TEXT,
            mimo_api_key_enc TEXT,
            gemini_api_key_enc TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    ''')
    conn.commit()

