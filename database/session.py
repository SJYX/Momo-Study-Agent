"""
database/session.py: 数据库上下文管理器与装饰器，消除冗余模板代码。
"""
from typing import Any, Callable, Dict, List, Optional, TypeVar, cast
import functools
import time

from database import connection
from database.utils import _is_sqlite_data_corruption_error, _debug_log, _backup_broken_database_file, _hash_fingerprint
from database.schema import _create_tables
import config as _config
from config import DATA_DIR
from core.logger import get_logger

try:
    import libsql
except Exception:
    libsql = None

T = TypeVar('T')

class DBSession:
    """包装了连接与防死锁机制的会话对象。

    读操作（fetchall / fetchone）支持锁超时降级：
    如果在 lock_timeout 秒内未能获取 _main_write_conn_op_lock，
    回退到不持锁直接执行 SQL。SQLite WAL 模式下读操作即使不持应用层锁也是安全的，
    最多读到旧数据，不会损坏或阻塞。

    写操作（execute / executemany）始终强制持锁，不降级。
    """

    # 默认读锁超时（秒）；写操作不使用此值
    DEFAULT_READ_LOCK_TIMEOUT = 2.0

    def __init__(self, conn: Any, lock: Any = None, lock_timeout: float = DEFAULT_READ_LOCK_TIMEOUT):
        self.conn = conn
        self.lock = lock
        self.lock_timeout = lock_timeout

    def _acquire_read_lock(self) -> bool:
        """尝试在 timeout 内获取读锁。

        Returns:
            True  — 成功获取锁（调用方需负责 release）
            False — 超时，已记录 WARNING，调用方应走无锁路径
        """
        if self.lock is None:
            return False
            
        # 对于主库/Hub库单例连接，读写复用同一连接对象，并发执行会导致 C 层 crash 或 SQL 事务损坏。
        # 我们必须死等/阻塞直至锁被释放，绝不能降级为无锁读取。
        is_singleton = connection._is_main_write_singleton_conn(self.conn) or connection._is_hub_write_singleton_conn(self.conn)
        if is_singleton:
            self.lock.acquire()  # 阻塞死等，防止并发冲突
            return True

        acquired = self.lock.acquire(timeout=self.lock_timeout)
        if not acquired:
            _debug_log(
                f"DBSession 读锁获取超时 ({self.lock_timeout}s)，降级为无锁读取",
                level="WARNING",
                module="database.session",
            )
        return acquired

    def fetchall(self, sql: str, params: tuple = ()) -> List[Any]:
        acquired = self._acquire_read_lock()
        try:
            cur = self.conn.cursor()
            try:
                cur.execute(sql, params)
                res = cur.fetchall()
            finally:
                cur.close()
            return res
        finally:
            if acquired:
                self.lock.release()

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[Any]:
        acquired = self._acquire_read_lock()
        try:
            cur = self.conn.cursor()
            try:
                cur.execute(sql, params)
                res = cur.fetchone()
            finally:
                cur.close()
            return res
        finally:
            if acquired:
                self.lock.release()
            
    def execute(self, sql: str, params: tuple = ()) -> None:
        if self.lock is not None:
            with self.lock:
                cur = self.conn.cursor()
                try:
                    cur.execute(sql, params)
                finally:
                    cur.close()
                self.conn.commit()
        else:
            cur = self.conn.cursor()
            try:
                cur.execute(sql, params)
            finally:
                cur.close()
            self.conn.commit()
            
    def executemany(self, sql: str, params_list: List[tuple]) -> None:
        if self.lock is not None:
            with self.lock:
                cur = self.conn.cursor()
                try:
                    cur.executemany(sql, params_list)
                finally:
                    cur.close()
                self.conn.commit()
        else:
            cur = self.conn.cursor()
            try:
                cur.executemany(sql, params_list)
            finally:
                cur.close()
            self.conn.commit()


def _attempt_auto_recovery(db_path: str) -> bool:
    """尝试自动修复损坏的 SQLite 数据库，优先使用云端数据重建，否则重新创建空表。"""
    try:
        from database.execution_engine import _release_db_file_handles_for_recovery
        _release_db_file_handles_for_recovery(db_path)
        backup_path = _backup_broken_database_file(db_path, "检测到本地数据库损坏，已备份本地数据库")
        if not backup_path:
            _debug_log("损坏库备份未完成（源文件可能被占用），继续尝试云端/本地重建", level="WARNING", module="database.session")

        ctx = connection._resolve_conn_context(db_path)
        if (connection.HAS_LIBSQL or connection.HAS_PYTURSO) and ctx.get("url") and ctx.get("token"):
            _debug_log(f"尝试从 Turso 云端重建损坏的数据库: {db_path}", level="INFO", module="database.session")
            repair_conn = connection._get_conn(db_path, allow_local_fallback=False, do_sync=True)
            try:
                if not connection._is_main_write_singleton_conn(repair_conn):
                    repair_conn.close()
            except Exception:
                pass
            return True

        _debug_log(f"没有云端凭证，尝试在本地重建空的数据库表: {db_path}", level="INFO", module="database.session")
        local_conn = connection._get_local_conn(db_path)
        try:
            _create_tables(local_conn.cursor())
            local_conn.commit()
        finally:
            try:
                local_conn.close()
            except Exception:
                pass
        return True
    except Exception as recovery_error:
        _debug_log(f"数据库自动恢复彻底失败: {recovery_error}", level="ERROR", module="database.session")
        return False


def with_read_session(default_return: Any = None, fallback_on_corruption: bool = True):
    """
    提供读连接会话的装饰器。
    
    业务函数需提供形如 `session: DBSession = None` 的参数（如果没有，装饰器会通过 kwargs 注入）。
    自动处理底层连接的获取、并发锁的包裹、异常（包括 SQLite 损坏兜底）以及单例的释放。
    包含一次自动重建损坏数据库并重试的机制。
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # 如果外界直接传了 session，就复用
            if 'session' in kwargs and kwargs['session'] is not None:
                return func(*args, **kwargs)
                
            db_path = kwargs.get('db_path') or _config.DB_PATH
            _recovery_attempted = kwargs.pop('_recovery_attempted', False)
            c = None
            try:
                started = time.time()
                c = connection._get_read_conn(db_path)
                conn_lock = connection._get_singleton_conn_op_lock(c)
                
                session = DBSession(c, conn_lock)
                kwargs['session'] = session
                
                res = func(*args, **kwargs)
                
                elapsed = int((time.time() - started) * 1000)
                if elapsed > 100:  # slow query logging
                    _debug_log(f"Slow Query in {func.__name__}: {elapsed}ms", level="DEBUG")
                    
                return res
            except Exception as e:
                if fallback_on_corruption and _is_sqlite_data_corruption_error(e):
                    if not _recovery_attempted:
                        get_logger().warning_throttled(
                            f"{func.__name__}_corruption_recovery",
                            f"{func.__name__} 检测到数据损坏: {e}，正在尝试自动恢复...",
                            module=func.__module__,
                        )

                        # 确保关闭损坏的连接后再恢复
                        try:
                            if c is not None and not connection._is_main_write_singleton_conn(c):
                                c.close()
                        except Exception:
                            pass

                        if _attempt_auto_recovery(db_path):
                            kwargs.pop('session', None)  # 移除旧的 session
                            kwargs['_recovery_attempted'] = True
                            return wrapper(*args, **kwargs) # 重试

                    get_logger().error_throttled(
                        f"{func.__name__}_corruption_final",
                        f"{func.__name__} 数据损坏且恢复失败: {e}",
                        module=func.__module__,
                    )
                    return default_return
                _debug_log(f"{func.__name__} 异常: {e}", level="WARNING", module=func.__module__)
                return default_return
            finally:
                if not _recovery_attempted or '_recovery_attempted' in kwargs: 
                    # 避免在重试的递归栈里重复关闭同一个连接（外层如果抛了异常才走到这）
                    try:
                        if c is not None and not connection._is_main_write_singleton_conn(c):
                            c.close()
                    except Exception:
                        pass
        return wrapper
    return decorator


def with_write_session(default_return: Any = None, fallback_on_corruption: bool = True):
    """提供直接写连接会话的装饰器（如果是通过 execution_engine，可能走 queue_write）"""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            if 'session' in kwargs and kwargs['session'] is not None:
                return func(*args, **kwargs)
                
            db_path = kwargs.get('db_path') or _config.DB_PATH
            c = None
            try:
                c = connection._get_conn(db_path)
                conn_lock = connection._get_singleton_conn_op_lock(c)
                session = DBSession(c, conn_lock)
                kwargs['session'] = session
                
                res = func(*args, **kwargs)
                
                from database.execution_engine import _mark_main_db_needs_sync
                _mark_main_db_needs_sync(db_path=db_path, conn=c)
                
                return res
            except Exception as e:
                if fallback_on_corruption and _is_sqlite_data_corruption_error(e):
                    get_logger().warning_throttled(
                        f"{func.__name__}_corruption",
                        f"{func.__name__} 写入数据损坏异常: {e}",
                        module=func.__module__,
                    )
                    return default_return
                _debug_log(f"{func.__name__} 写入异常: {e}", level="WARNING", module=func.__module__)
                return default_return
            finally:
                try:
                    if c is not None and not connection._is_main_write_singleton_conn(c):
                        c.close()
                except Exception:
                    pass
        return wrapper
    return decorator
