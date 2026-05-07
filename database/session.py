"""
database/session.py: 数据库上下文管理器与装饰器，消除冗余模板代码。
"""
from typing import Any, Callable, Dict, List, Optional, TypeVar, cast
import functools
import time

from database import connection
from database.utils import _is_sqlite_data_corruption_error, _debug_log, _debug_log_throttled
from core.logger import get_logger

T = TypeVar('T')

class DBSession:
    """包装了连接与防死锁机制的会话对象"""
    def __init__(self, conn: Any, lock: Any = None):
        self.conn = conn
        self.lock = lock

    def fetchall(self, sql: str, params: tuple = ()) -> List[Any]:
        if self.lock is not None:
            with self.lock:
                cur = self.conn.cursor()
                try:
                    cur.execute(sql, params)
                    res = cur.fetchall()
                finally:
                    cur.close()
                self.conn.commit()
                return res
        else:
            cur = self.conn.cursor()
            try:
                cur.execute(sql, params)
                res = cur.fetchall()
            finally:
                cur.close()
            self.conn.commit()
            return res

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[Any]:
        if self.lock is not None:
            with self.lock:
                cur = self.conn.cursor()
                try:
                    cur.execute(sql, params)
                    res = cur.fetchone()
                finally:
                    cur.close()
                self.conn.commit()
                return res
        else:
            cur = self.conn.cursor()
            try:
                cur.execute(sql, params)
                res = cur.fetchone()
            finally:
                cur.close()
            self.conn.commit()
            return res
            
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


def with_read_session(default_return: Any = None, fallback_on_corruption: bool = True):
    """
    提供读连接会话的装饰器。
    
    业务函数需提供形如 `session: DBSession = None` 的参数（如果没有，装饰器会通过 kwargs 注入）。
    自动处理底层连接的获取、并发锁的包裹、异常（包括 SQLite 损坏兜底）以及单例的释放。
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # 如果外界直接传了 session，就复用
            if 'session' in kwargs and kwargs['session'] is not None:
                return func(*args, **kwargs)
                
            db_path = kwargs.get('db_path') or connection.DB_PATH
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
                    _debug_log_throttled(
                        f"{func.__name__}_corruption",
                        f"{func.__name__} 数据损坏异常: {e}",
                        level="WARNING",
                        module=func.__module__
                    )
                    return default_return
                _debug_log(f"{func.__name__} 异常: {e}", level="WARNING", module=func.__module__)
                return default_return
            finally:
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
                
            db_path = kwargs.get('db_path') or connection.DB_PATH
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
                    _debug_log_throttled(
                        f"{func.__name__}_corruption",
                        f"{func.__name__} 写入数据损坏异常: {e}",
                        level="WARNING",
                        module=func.__module__
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
